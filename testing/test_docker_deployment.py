import ast
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import shlex
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def deployment_helpers():
    script = (ROOT / 'deploy_docker.example.ps1').read_text(encoding='utf-8')
    source = re.search(r"\$remoteCode = @'\n(.*?)\n'@", script, re.S)[1]
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
             or isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in {'IMAGE', 'SUPPORT_FILES'}
                 for target in node.targets)]
    namespace = {'ROOT': ROOT}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<deployment helpers>', 'exec'), namespace)
    return namespace, tree


class DockerDeploymentTests(unittest.TestCase):
    def test_install_preserves_env_and_uses_only_latest_without_linux_build(self):
        helpers, _ = deployment_helpers()
        command = helpers['install_command']('/tmp/logcomparator-deploy.fixture',
                                              "/home/user/project's folder", 'compose.yaml')
        self.assertIn("cd "+shlex.quote("/home/user/project's folder"), command)
        self.assertIn('docker load -i logcomparator.tar', command)
        self.assertIn('sh ./docker_compose.sh -f compose.yaml config --quiet', command)
        self.assertIn('sh ./docker_compose.sh -f compose.yaml up', command)
        self.assertIn('docker_compose.sh', helpers['SUPPORT_FILES'])
        self.assertIn('docker image inspect logcomparator_iarv:latest', command)
        self.assertIn('--no-build --pull never --force-recreate logcomparator', command)
        self.assertNotIn('docker build', command)
        self.assertNotIn('docker tag', command)
        self.assertNotIn('pip install', command)
        destinations = [shlex.split(line)[-1] for line in command.splitlines()
                        if line.startswith('mv -f --')]
        self.assertNotIn('.env', destinations)
        self.assertEqual(set(destinations), {'logcomparator.tar', *helpers['SUPPORT_FILES']})

    def test_parent_paths_are_rejected(self):
        helpers, _ = deployment_helpers()
        for path in ('/', '/tmp', 'project', '/opt/../etc', '/opt/app\ncommand'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                helpers['remote_directory'](path)

    def test_scp_checksum_is_verified_before_install_and_stage_is_cleaned(self):
        helpers, _ = deployment_helpers()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'logcomparator.tar'
            archive.write_bytes(b'complete test image')
            for correct in (True, False):
                calls, uploads = [], []

                def remote(client, command, **kwargs):
                    calls.append(command)
                    if command.startswith('mktemp'):
                        return '/tmp/logcomparator-deploy.fixture\n'
                    if command.startswith('sha256sum'):
                        return (helpers['archive_digest'](archive) if correct else 'wrong')+'  file\n'
                    return ''

                scp = Mock()
                scp.__enter__ = Mock(return_value=scp)
                scp.__exit__ = Mock(return_value=False)
                scp.put.side_effect = lambda source, remote_path: uploads.append((source, remote_path))
                with patch.dict(helpers, ssh_command=remote, SCPClient=Mock(return_value=scp)), redirect_stdout(io.StringIO()):
                    run = lambda: helpers['upload_and_install'](Mock(), Mock(sudo_password='test-only'),
                               archive, '/opt/LogComparator', 'compose.remote.yaml')
                    if correct:
                        run()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                            run()
                self.assertEqual(len(uploads), 1 + len(helpers['SUPPORT_FILES']))
                self.assertEqual(any('docker load' in command for command in calls), correct)
                self.assertTrue(calls[-1].startswith('rm -f --'))
                self.assertNotIn('rm -rf', calls[-1])

    def test_health_checks_https_using_the_application_checker(self):
        helpers, _ = deployment_helpers()
        remote = Mock(return_value='{"app":"LogComparator","version":"test-version"}')
        with patch.dict(helpers, ssh_command=remote):
            result = helpers['wait_for_health'](Mock(), Mock(sudo_password='test-only'))
        self.assertEqual(result['version'], 'test-version')
        self.assertIn('from web_tls import check_health', remote.call_args.args[1])

    def test_template_has_no_configured_password_and_local_script_is_ignored(self):
        import log_core as core
        script = (ROOT / 'deploy_docker.example.ps1').read_text()
        self.assertIn("$SshPassword = '__DEPLOY_PASSWORD__'", script)
        self.assertFalse(core.RUNTIME_SETTINGS.sudo_password in script,
                         'The deployment template must not contain the configured password.')
        for name in ('.gitignore', '.dockerignore'):
            self.assertIn('deploy_docker.ps1', (ROOT / name).read_text().splitlines())

    def test_remote_preflight_contains_real_newlines(self):
        _, tree = deployment_helpers()
        assignment = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.Assign) and any(
                              isinstance(target, ast.Name) and target.id == 'preflight'
                              for target in node.targets))
        expression = compile(ast.Expression(assignment.value), '<preflight>', 'eval')
        command = eval(expression, {'shlex': shlex, 'destination': '/opt/LogComparator'})
        self.assertTrue(command.startswith('set -eu\ncd '))
        self.assertNotIn('\\n', command)

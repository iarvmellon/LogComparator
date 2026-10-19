// Run inside the user's click gesture, without a server or export round trip.
window.logComparatorOpenTabs = function (urls) {
  const blocked = [];
  for (const url of urls) {
    const tab = window.open(url, '_blank');
    if (tab) tab.opener = null;
    else blocked.push(url);
  }
  return blocked;
};

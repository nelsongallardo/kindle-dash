async page => {
  const tab = await page.context().newPage();
  const bodies = [];
  tab.on('response', async response => {
    if (/\/graphql\/[^/]+\/HomeLatestTimeline/.test(response.url())) {
      try { bodies.push(await response.json()); } catch (e) {}
    }
  });
  try {
    await tab.goto('https://x.com/home');
    await tab.waitForTimeout(4000);
    const following = tab.getByRole('tab', {name: 'Following'});
    if (await following.count()) { await following.click(); await tab.waitForTimeout(4000); }
    for (let i = 0; i < 4; i++) { await tab.mouse.wheel(0, 2500); await tab.waitForTimeout(1500); }
    return JSON.stringify(bodies);
  } finally {
    await tab.close();
  }
}

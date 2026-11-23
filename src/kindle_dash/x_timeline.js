async page => {
  const tab = await page.context().newPage();
  let bodies = [];
  tab.on('response', async response => {
    if (/\/graphql\/[^/]+\/Home\w*Timeline/.test(response.url())) {
      try { bodies.push(await response.json()); } catch (e) {}
    }
  });
  try {
    await tab.goto('https://x.com/home');
    await tab.waitForTimeout(4000);
    const following = tab.getByRole('tab', {name: 'Following'});
    if (await following.getAttribute('aria-selected') !== 'true') {
      await following.click();
      await tab.waitForTimeout(3000);
    }
    // Clicking the selected Following tab opens X's "Sort by: Popular / Recent" menu.
    await following.click();
    await tab.locator('#layers [role=menuitem]', {hasText: 'Recent'}).click();
    await tab.waitForTimeout(2000);
    bodies = [];
    await tab.reload();
    await tab.waitForTimeout(5000);
    for (let i = 0; i < 4; i++) { await tab.mouse.wheel(0, 2500); await tab.waitForTimeout(1500); }
    return JSON.stringify(bodies);
  } finally {
    await tab.close();
  }
}

// Lighthouse CI puppeteerScript: sets the session cookie so /app routes render instead of redirecting to sign-in.
// Against a real backend use a real session value: LHCI_SESSION=<cookie value>.
module.exports = async (browser) => {
  const page = await browser.newPage()
  // Cookies do not depend on the port, so this covers :3000 and the :3400 Lighthouse front alike.
  await page.setCookie({ name: 'actron_session', value: process.env.LHCI_SESSION || 'lighthouse', url: 'http://127.0.0.1:3000' })
  await page.close()
}

import { chromium } from 'playwright';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  // Set window viewport size
  await page.setViewportSize({ width: 1280, height: 800 });
  
  console.log('Navigating to http://localhost:5173/...');
  await page.goto('http://localhost:5173/');
  
  console.log('Waiting for "调试进入主页面" button...');
  const debugBtn = page.locator('button:has-text("调试进入主页面")');
  await debugBtn.waitFor({ timeout: 5000 });
  
  console.log('Clicking "调试进入主页面"...');
  await debugBtn.click();
  
  console.log('Waiting for transition...');
  // Wait for 3 seconds for the transition animations to finish
  await page.waitForTimeout(3000);
  
  console.log('Taking screenshot of the main interface...');
  await page.screenshot({ path: 'e:/code/warp_te/----agent/.playwright-mcp/main-page-screenshot.png' });
  
  await browser.close();
  console.log('Done!');
}

run().catch(err => {
  console.error(err);
  process.exit(1);
});

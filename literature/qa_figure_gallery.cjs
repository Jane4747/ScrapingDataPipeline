// Offline browser QA for the generated figure and image library.
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{
 const root=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.LITERATURE_BROWSER || 'E:/CAICTBigData/coding/.playwright-browsers/chromium_headless_shell-1248/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 const page=await browser.newPage({viewport:{width:1280,height:1000},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(root,'index.html')).href);
 const cards=await page.locator('.card').count();
 if(cards!==manifest.figure_count)throw new Error('Figure card count mismatch');
 const papers=await page.locator('section').count();
 if(papers!==22)throw new Error('Paper count mismatch');
 await page.locator('img').first().waitFor({state:'visible'});
 await page.screenshot({path:path.join(out,'figure-gallery-desktop.png')});
 await page.locator('#search').fill('AdaRSI');
 const filtered=await page.locator('.card:visible').count();
 if(!(filtered>0&&filtered<cards))throw new Error('Search did not filter');
 await page.locator('#search').fill('definitely-no-paper-matches-this-string');
 if(await page.locator('.card:visible').count()!==0)throw new Error('Empty search result');
 await page.locator('#search').fill('');
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'figure-gallery-mobile.png')});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Mobile overflow');
 const links=await page.locator('a[href],img[src]').evaluateAll(es=>es.map(e=>e.getAttribute('href')||e.getAttribute('src')).filter(h=>h&&!h.startsWith('#')&&!h.startsWith('http')));
 const missing=[...new Set(links)].filter(h=>!fs.existsSync(path.resolve(root,h)));
 if(missing.length)throw new Error('Missing links: '+missing.slice(0,5).join(','));
 await page.goto(pathToFileURL(path.join(root,'embedded_images.html')).href);
 const assets=await page.locator('.card').count();
 if(assets!==manifest.unique_embedded_images)throw new Error('Asset card count mismatch');
 if(errors.length)throw new Error(errors.join('\n'));
 fs.writeFileSync(path.join(out,'browser_verification.json'),JSON.stringify({status:'passed',papers,figure_cards:cards,embedded_asset_cards:assets,search:true,mobile_overflow:false,local_links:true,script_errors:errors},null,2));
 await browser.close();console.log('Figure gallery browser checks passed');
})().catch(e=>{console.error(e);process.exit(1)});


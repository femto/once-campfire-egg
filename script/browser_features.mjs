// Run against a disposable fresh app; uses the verification repo's Playwright.
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
const require = createRequire(resolve(process.env.CAMPFIRE_VERIFICATION || '../once-campfire-verification', 'package.json'))
const { chromium } = require('playwright')
const base = process.argv[process.argv.indexOf('--base') + 1]
if (!base?.startsWith('http')) throw new Error('--base URL required')
const errors=[]
const browser=await chromium.launch({headless:true})
try {
  const context=await browser.newContext({baseURL:base})
  const page=await context.newPage()
  page.on('pageerror',error=>errors.push(error.message))
  const setup=await context.request.post('/first_run',{form:{'user[name]':'Browser Media','user[email_address]':'media@example.test','user[password]':'password123'}})
  if(!setup.ok()) throw new Error('setup failed')
  const png=execFileSync('convert',['-size','800x400','xc:red','png:-'])
  await page.goto('/users/me/profile')
  await page.locator('input[name="user[avatar]"]').first().setInputFiles({name:'avatar.png',mimeType:'image/png',buffer:png})
  await page.locator('#flash-notice').filter({hasText:'Image updated'}).waitFor()
  await page.reload()
  await page.waitForFunction(()=>document.querySelector('[data-upload-preview-target="image"]').naturalWidth===512)
  await page.goto('/account/edit')
  await page.locator('input[name="account[logo]"]').setInputFiles({name:'logo.png',mimeType:'image/png',buffer:png})
  await page.locator('#flash-notice').filter({hasText:'Image updated'}).waitFor()
  await page.reload()
  await page.waitForFunction(()=>document.querySelector('img[alt="Account logo"]').naturalWidth===512)
  await page.goto('/rooms/1')
  await page.locator('#composer input[type=file]').setInputFiles({name:'chat-photo.png',mimeType:'image/png',buffer:png})
  await page.getByRole('button',{name:'Send Message',exact:true}).click()
  const preview=page.locator('.message .attachment img').last()
  await preview.waitFor()
  await page.waitForFunction(()=>Array.from(document.querySelectorAll('.message .attachment img')).some(image=>image.complete&&image.naturalWidth>0))
  const fileLink=page.locator('.message .attachment a').filter({hasText:'chat-photo.png'}).last()
  if(!(await context.request.get(await fileLink.getAttribute('href'))).ok()) throw new Error('attachment download failed')
  if(errors.length) throw new Error(errors.join('\n'))
  console.log('PASS: browser avatar/logo forms, visible Flash, composer upload and loaded media preview')
} finally { await browser.close() }

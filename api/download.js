import axios from 'axios';

// Upstash Redis Helper via REST API
async function upstashRedis(command, ...args) {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;

  if (!url || !token) return null;

  try {
    const res = await fetch(`${url}/${command}/${args.join('/')}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const data = await res.json();
    return data.result;
  } catch (err) {
    console.error('Upstash Error:', err);
    return null;
  }
}

// SnapSave / FB Downloader Parser
async function parseFbVideo(fbUrl) {
  const params = new URLSearchParams();
  params.append('q', fbUrl);
  params.append('vt', 'facebook');

  const res = await axios.post('https://snapsave.app/action.php', params, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
      'Origin': 'https://snapsave.app',
      'Referer': 'https://snapsave.app/',
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    timeout: 10000
  });

  const html = res.data;

  // Extract links from response HTML or obfuscated script
  const hdMatch = html.match(/href="(https:\/\/[^"]+)"[^>]*>Render HD/i) || 
                  html.match(/href="(https:\/\/[^"]+)"[^>]*>Download HD/i) ||
                  html.match(/https:\/\/[^"'\s]+\.mp4[^"'\s]*/gi);

  const sdMatch = html.match(/href="(https:\/\/[^"]+)"[^>]*>Download SD/i) ||
                  html.match(/href="(https:\/\/[^"]+)"[^>]*>Download/i);

  let hdUrl = null;
  let sdUrl = null;

  if (Array.isArray(hdMatch)) {
    hdUrl = hdMatch[0].replace(/&amp;/g, '&');
  }
  if (Array.isArray(sdMatch)) {
    sdUrl = sdMatch[1] ? sdMatch[1].replace(/&amp;/g, '&') : sdMatch[0].replace(/&amp;/g, '&');
  }

  return { hdUrl, sdUrl };
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method === 'GET') {
    const count = await upstashRedis('get', 'fb_download_count');
    return res.status(200).json({ success: true, count: Number(count || 0) });
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, message: 'Method Not Allowed' });
  }

  const { url } = req.body || {};

  if (!url || (!url.includes('facebook.com') && !url.includes('fb.watch'))) {
    return res.status(400).json({ success: false, message: 'Maglagay ng valid na Facebook video URL.' });
  }

  try {
    let hdUrl = null;
    let sdUrl = null;

    // Method 1: SnapSave Action Engine
    try {
      const parsed = await parseFbVideo(url);
      hdUrl = parsed.hdUrl;
      sdUrl = parsed.sdUrl;
    } catch (e) {
      console.log('SnapSave engine failed, falling back to public API...');
    }

    // Method 2: Public Rapid Scraping Fallback
    if (!hdUrl && !sdUrl) {
      try {
        const fbRes = await axios.get(`https://api.vytal.cx/fb?url=${encodeURIComponent(url)}`, { timeout: 7000 });
        hdUrl = fbRes.data?.hd || fbRes.data?.downloads?.hd;
        sdUrl = fbRes.data?.sd || fbRes.data?.downloads?.sd;
      } catch (e) {}
    }

    if (!hdUrl && !sdUrl) {
      return res.status(404).json({
        success: false,
        message: 'Hindi ma-extract ang video. Pakisiguradong Public Post / Reel ang link.'
      });
    }

    // Increment download counter
    const totalDownloads = await upstashRedis('incr', 'fb_download_count');

    return res.status(200).json({
      success: true,
      title: 'Facebook_Video',
      thumbnail: '',
      downloads: {
        hd: hdUrl,
        sd: sdUrl || hdUrl
      },
      totalDownloads: totalDownloads || 0
    });

  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Extraction Error: ' + (error.message || 'Hindi ma-process ang video.')
    });
  }
}

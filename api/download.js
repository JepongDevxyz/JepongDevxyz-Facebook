import axios from 'axios';

// Native Upstash REST Helper
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
    // External API Scraper (SnapSave-based endpoint)
    const response = await axios.get(`https://api.vytal.to/fb?url=${encodeURIComponent(url)}`, {
      timeout: 12000,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
      }
    });

    const data = response.data;

    if (!data || !data.downloads || (!data.downloads.hd && !data.downloads.sd)) {
      // Fallback extraction query kung may ibang format
      if (data && (data.hd || data.sd)) {
        data.downloads = { hd: data.hd, sd: data.sd };
      } else {
        return res.status(404).json({
          success: false,
          message: 'Hindi ma-extract ang video. Siguraduhing Public ang post at hindi Private group video.'
        });
      }
    }

    // Increment count via REST
    const totalDownloads = await upstashRedis('incr', 'fb_download_count');

    return res.status(200).json({
      success: true,
      title: data.title || 'Facebook_Video',
      thumbnail: data.thumbnail || '',
      downloads: {
        hd: data.downloads.hd || null,
        sd: data.downloads.sd || data.downloads.hd
      },
      totalDownloads: totalDownloads || 0
    });

  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Extraction Error: ' + (error.response?.data?.message || error.message)
    });
  }
}

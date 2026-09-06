import axios from 'axios';

// Upstash Redis Helper
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
    // Primary Engine: Public Cobalt Instances (Most Reliable for FB/Reels)
    const instances = [
      'https://cobalt-api.kwiatek.xyz',
      'https://api.cobalt.tools',
      'https://cobalt.xy2.dev'
    ];

    let videoUrl = null;

    for (const instance of instances) {
      try {
        const response = await axios.post(
          instance,
          { url: url, videoQuality: 'max' },
          {
            headers: {
              'Accept': 'application/json',
              'Content-Type': 'application/json',
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            },
            timeout: 8000
          }
        );

        if (response.data && response.data.url) {
          videoUrl = response.data.url;
          break;
        }
      } catch (e) {
        continue; // Subukan ang kasunod na instance kapag nag-fail
      }
    }

    if (!videoUrl) {
      return res.status(404).json({
        success: false,
        message: 'Hindi ma-extract ang video. Siguraduhing public video o reel ang link at hindi private group.'
      });
    }

    // Increment download counter
    const totalDownloads = await upstashRedis('incr', 'fb_download_count');

    return res.status(200).json({
      success: true,
      title: 'Facebook_Video',
      thumbnail: '',
      downloads: {
        hd: videoUrl,
        sd: videoUrl
      },
      totalDownloads: totalDownloads || 0
    });

  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Server Error: ' + (error.message || 'Hindi ma-process ang request.')
    });
  }
}

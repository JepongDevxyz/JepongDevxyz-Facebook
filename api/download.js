import axios from 'axios';
import * as cheerio from 'cheerio';
import { Redis } from '@upstash/redis';

// Safe Redis Initialization
let redis = null;
try {
  if (process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN) {
    redis = Redis.fromEnv();
  }
} catch (e) {
  console.error("Redis init error:", e);
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // GET Request: Safe Counter Fetch
  if (req.method === 'GET') {
    try {
      if (redis) {
        const count = (await redis.get('fb_download_count')) || 0;
        return res.status(200).json({ success: true, count: Number(count) });
      }
      return res.status(200).json({ success: true, count: 0 });
    } catch (err) {
      return res.status(200).json({ success: true, count: 0 });
    }
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, message: 'Method Not Allowed' });
  }

  const { url } = req.body || {};

  if (!url || (!url.includes('facebook.com') && !url.includes('fb.watch'))) {
    return res.status(400).json({ success: false, message: 'Maglagay ng valid na Facebook video URL.' });
  }

  try {
    const response = await axios.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Mode': 'navigate'
      },
      timeout: 10000
    });

    const html = response.data;
    const $ = cheerio.load(html);

    const rawTitle = $('meta[property="og:title"]').attr('content') || 
                     $('title').text() || 
                     'Facebook_Video';
    const thumbnail = $('meta[property="og:image"]').attr('content') || '';

    const hdMatch = html.match(/"browser_native_hd_url":"([^"]+)"/) || 
                    html.match(/hd_src:"([^"]+)"/) ||
                    html.match(/"playable_url_quality_hd":"([^"]+)"/);

    const sdMatch = html.match(/"browser_native_sd_url":"([^"]+)"/) || 
                    html.match(/sd_src:"([^"]+)"/) ||
                    html.match(/"playable_url":"([^"]+)"/);

    const cleanUrl = (str) => str ? str.replace(/\\/g, '').replace(/&amp;/g, '&') : null;

    const hdUrl = hdMatch ? cleanUrl(hdMatch[1]) : null;
    const sdUrl = sdMatch ? cleanUrl(sdMatch[1]) : null;

    if (!hdUrl && !sdUrl) {
      return res.status(404).json({
        success: false,
        message: 'Hindi makuha ang video. Maaaring naka-private, may restriction, o pinalitan ng Facebook ang structure.'
      });
    }

    // Safe Increment sa Redis
    let totalDownloads = 0;
    if (redis) {
      try {
        totalDownloads = await redis.incr('fb_download_count');
      } catch (redisErr) {
        console.error('Redis Increment Error:', redisErr);
      }
    }

    const cleanTitle = rawTitle.replace(/[^\w\s-]/gi, '').trim() || 'Facebook_Video';

    return res.status(200).json({
      success: true,
      title: cleanTitle,
      thumbnail: thumbnail,
      downloads: {
        hd: hdUrl,
        sd: sdUrl || hdUrl
      },
      totalDownloads
    });

  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Failed to fetch video details: ' + (error.response?.statusText || error.message)
    });
  }
}

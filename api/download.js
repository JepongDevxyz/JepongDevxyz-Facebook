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
    // Primary API Service for FB Video Parsing
    const apiUrl = `https://api.vytal.cx/fb?url=${encodeURIComponent(url)}`;
    
    // Backup API Service
    const backupApiUrl = `https://fdown-api.vercel.app/api/download?url=${encodeURIComponent(url)}`;

    let videoData = null;

    try {
      const response = await axios.get(apiUrl, { timeout: 8000 });
      if (response.data && (response.data.hd || response.data.sd || response.data.downloads)) {
        videoData = response.data;
      }
    } catch (e) {
      console.log('Primary API failed, trying backup...');
    }

    // Fallback kung nag-fail ang primary
    if (!videoData) {
      const backupResponse = await axios.get(backupApiUrl, { timeout: 8000 });
      videoData = backupResponse.data;
    }

    const hdUrl = videoData?.downloads?.hd || videoData?.hd || null;
    const sdUrl = videoData?.downloads?.sd || videoData?.sd || hdUrl;

    if (!hdUrl && !sdUrl) {
      return res.status(404).json({
        success: false,
        message: 'Hindi ma-extract ang video. Siguraduhing Public ang post at pampublikong FB page/profile ito.'
      });
    }

    // Increment download counter
    const totalDownloads = await upstashRedis('incr', 'fb_download_count');

    return res.status(200).json({
      success: true,
      title: videoData.title || 'Facebook_Video',
      thumbnail: videoData.thumbnail || videoData.thumb || '',
      downloads: {
        hd: hdUrl,
        sd: sdUrl
      },
      totalDownloads: totalDownloads || 0
    });

  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Extraction Error: Hindi makuha ang video link. Subukan ang ibang Facebook Video URL.'
    });
  }
}

import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();

// v11: per-platform counter — 'reddit' lang ang may sariling key
// ("counter:reddit"); ang default ("global_downloads") ay ang
// Facebook counter pa rin (hindi ni-reset ang bilang).
// TANDAAN: ang live /api/counter ay ITO ang nagsisilbi (Vercel
// filesystem routing — api/counter.js), HINDI ang /api/counter ng
// main.py (FastAPI). Kaya dito ang platform support, hindi sa main.py.
function keyFor(req) {
  const platform = (req.query && req.query.platform) || '';
  return platform === 'reddit' ? 'counter:reddit' : 'global_downloads';
}

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST');

  try {
    const key = keyFor(req);
    if (req.method === 'POST') {
      const newCount = await redis.incr(key);
      return res.status(200).json({ status: 'success', count: newCount });
    }

    const count = (await redis.get(key)) || 0;
    return res.status(200).json({ status: 'success', count: Number(count) });
  } catch (error) {
    return res.status(500).json({ status: 'error', message: error.message });
  }
}

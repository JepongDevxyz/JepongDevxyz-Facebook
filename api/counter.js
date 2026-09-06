import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST');

  try {
    if (req.method === 'POST') {
      const newCount = await redis.incr('global_downloads');
      return res.status(200).json({ status: 'success', count: newCount });
    }

    const count = (await redis.get('global_downloads')) || 0;
    return res.status(200).json({ status: 'success', count: Number(count) });
  } catch (error) {
    return res.status(500).json({ status: 'error', message: error.message });
  }
}

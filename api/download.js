import ytDlp from 'yt-dlp-exec';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method Not Allowed' });
  }

  const { url, quality } = req.body || {};

  if (!url || !url.includes('facebook.com')) {
    return res.status(400).json({
      status: 'error',
      message: 'Failed to extract video information: Please provide a valid Facebook video URL.'
    });
  }

  try {
    // Map UI quality options to yt-dlp format selection
    let formatFilter = 'bestvideo+bestaudio/best';
    if (quality === '1080p') formatFilter = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]';
    if (quality === '720p') formatFilter = 'bestvideo[height<=720]+bestaudio/best[height<=720]';
    if (quality === '360p') formatFilter = 'bestvideo[height<=360]+bestaudio/best[height<=360]';
    if (quality === 'worst') formatFilter = 'worstvideo+worstaudio/worst';

    // Extract metadata gamit ang yt-dlp
    const output = await ytDlp(url, {
      dumpSingleJson: true,
      noWarnings: true,
      noCallHome: true,
      noCheckCertificate: true,
      format: formatFilter,
      preferFreeFormats: true,
      youtubeSkipDashManifest: true
    });

    // Formatting duration (Seconds to Min:Sec string)
    const durationSec = output.duration || 0;
    const minutes = Math.floor(durationSec / 60);
    const seconds = Math.floor(durationSec % 60);
    const formattedDuration = `${minutes}:${seconds < 10 ? '0' : ''}${seconds} Min`;

    return res.status(200).json({
      status: 'success',
      video_info: {
        title: output.title || output.fulltitle || 'Facebook Video',
        duration: formattedDuration,
        uploader: output.uploader || output.webpage_url_domain || 'Facebook User',
        view_count: output.view_count || 0
      },
      download_url: output.url || (output.formats && output.formats[0]?.url) || url
    });

  } catch (error) {
    console.error('yt-dlp Error:', error);
    return res.status(500).json({
      status: 'error',
      message: 'Failed to extract video information: This video is private or not available for download.'
    });
  }
}

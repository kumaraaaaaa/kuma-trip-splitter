// api/hello.js
// 這裡可以讀取 Vercel 設定好的環境變數 (在 Vercel Dashboard 設定)
export default function handler(request, response) {
  const { name } = request.query;

  // 讀取環境變數範例
  const apiKey = process.env.MY_API_KEY;

  response.status(200).json({
    message: `你好，${name || '訪客'}！`,
    status: 'API 運作正常',
    envCheck: apiKey ? 'API Key 已讀取' : 'API Key 未找到'
  });
}
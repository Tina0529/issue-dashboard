// Netlify Function: 触发 GitHub Actions Workflow
exports.handler = async (event, context) => {
  // 只允许 POST 请求
  if (event.httpMethod !== 'POST') {
    return {
      statusCode: 405,
      body: JSON.stringify({ error: 'Method not allowed' })
    };
  }

  // 支持多种变量名
  const GITHUB_TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || process.env.GH_PAT;
  const REPO_OWNER = 'Tina0529';
  const REPO_NAME = 'issue-dashboard';
  const WORKFLOW_ID = 'update.yml';

  // 调试日志
  console.log('Environment check:', {
    hasGITHUB_TOKEN: !!process.env.GITHUB_TOKEN,
    hasGH_TOKEN: !!process.env.GH_TOKEN,
    hasGH_PAT: !!process.env.GH_PAT,
    tokenLength: GITHUB_TOKEN ? GITHUB_TOKEN.length : 0,
    allEnvKeys: Object.keys(process.env).filter(k => k.includes('GIT') || k.includes('GH') || k.includes('TOKEN'))
  });

  if (!GITHUB_TOKEN) {
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        error: 'GitHub token not configured',
        hint: 'Please add GITHUB_TOKEN or GH_TOKEN in Netlify Environment Variables with Functions scope'
      })
    };
  }

  try {
    // 触发 workflow_dispatch
    const response = await fetch(
      `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ref: 'main'
        })
      }
    );

    console.log('GitHub API response status:', response.status);

    if (response.status === 204) {
      return {
        statusCode: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({
          success: true,
          message: 'Workflow triggered successfully',
          timestamp: new Date().toISOString()
        })
      };
    } else {
      const errorText = await response.text();
      console.log('GitHub API error:', errorText);
      return {
        statusCode: response.status,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({
          error: 'Failed to trigger workflow',
          details: errorText
        })
      };
    }
  } catch (error) {
    console.error('Function error:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ error: error.message })
    };
  }
};

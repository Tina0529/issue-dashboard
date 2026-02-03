// Netlify Function: 触发 GitHub Actions Workflow
exports.handler = async (event, context) => {
  // 只允许 POST 请求
  if (event.httpMethod !== 'POST') {
    return {
      statusCode: 405,
      body: JSON.stringify({ error: 'Method not allowed' })
    };
  }

  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  const REPO_OWNER = 'Tina0529';
  const REPO_NAME = 'issue-dashboard';
  const WORKFLOW_ID = 'update.yml';

  if (!GITHUB_TOKEN) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: 'GitHub token not configured' })
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
      return {
        statusCode: response.status,
        body: JSON.stringify({
          error: 'Failed to trigger workflow',
          details: errorText
        })
      };
    }
  } catch (error) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: error.message })
    };
  }
};

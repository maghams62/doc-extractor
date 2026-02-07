import { spawn } from 'child_process';
import http from 'http';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const repoRoot = path.resolve(__dirname, '../../../../');
const backendDir = path.join(repoRoot, 'app', 'backend');
const frontendDir = path.join(repoRoot, 'app', 'frontend');
const backendPort = process.env.E2E_BACKEND_PORT || '8000';
const frontendPort = process.env.E2E_FRONTEND_PORT || '5173';
const backendHost = process.env.E2E_BACKEND_HOST || '127.0.0.1';
const frontendHost = process.env.E2E_FRONTEND_HOST || '127.0.0.1';
const apiBase = `http://${backendHost}:${backendPort}`;
const formHtmlPath = path.join(repoRoot, 'app', 'backend', 'tests', 'fixtures', 'form.html');
const formUrl = pathToFileURL(formHtmlPath).toString();

const useRealLlmRequested = process.env.E2E_USE_REAL_LLM === '1';
const hasApiKey = Boolean(process.env.OPENAI_API_KEY || process.env.LLM_API_KEY);

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth() {
  const maxAttempts = 120;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const ok = await new Promise((resolve) => {
      const req = http.get(`${apiBase}/health`, (res) => {
        res.resume();
        resolve(res.statusCode && res.statusCode >= 200 && res.statusCode < 300);
      });
      req.on('error', () => resolve(false));
    });
    if (ok) return;
    await delay(1000);
  }
  throw new Error(`Backend health check failed at ${apiBase}/health`);
}

function createMockResponse(body) {
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  const userMessage = messages.find((msg) => msg.role === 'user')?.content || '';

  if (userMessage.includes('Translate the following OCR text into English')) {
    const marker = 'OCR text:';
    const idx = userMessage.indexOf(marker);
    const ocrText = idx >= 0 ? userMessage.slice(idx + marker.length).trim() : '';
    const content = ocrText || 'Translated text.';
    return { content };
  }

  const suggestion = [
    {
      field: 'g28.attorney.email',
      verdict: 'green',
      score: 0.96,
      reason: 'Normalized email spacing.',
      suggested_value: 'immigration@tryalma.ai',
      suggested_value_reason: 'Removed whitespace around @.',
      evidence: 'immigration@tryalma.ai',
      requires_human_input: false,
    },
  ];
  return { content: JSON.stringify(suggestion) };
}

function startMockLlmServer(port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
        res.statusCode = 404;
        res.end('Not found');
        return;
      }
      let payload = '';
      req.on('data', (chunk) => {
        payload += chunk;
      });
      req.on('end', () => {
        let body = {};
        try {
          body = JSON.parse(payload || '{}');
        } catch (error) {
          body = {};
        }
        const { content } = createMockResponse(body);
        const response = {
          id: 'mock-llm',
          object: 'chat.completion',
          created: Math.floor(Date.now() / 1000),
          model: body.model || 'mock-llm',
          choices: [
            {
              index: 0,
              message: { role: 'assistant', content },
              finish_reason: 'stop',
            },
          ],
        };
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify(response));
      });
    });

    server.listen(port, backendHost, () => {
      console.log(`[e2e] Mock LLM listening on http://${backendHost}:${port}`);
      resolve(server);
    });
  });
}

function spawnProcess(label, command, args, options) {
  const child = spawn(command, args, { stdio: 'inherit', ...options });
  child.on('exit', (code) => {
    if (code && code !== 0) {
      console.error(`[e2e] ${label} exited with code ${code}`);
      process.exit(code);
    }
  });
  return child;
}

async function main() {
  let useRealLlm = useRealLlmRequested;
  if (useRealLlmRequested && !hasApiKey) {
    console.warn('[e2e] E2E_USE_REAL_LLM is set but no API key found; falling back to mock.');
    useRealLlm = false;
  }

  let mockServer = null;
  let llmEndpoint = null;
  if (!useRealLlm) {
    const mockPort = Number(process.env.E2E_MOCK_LLM_PORT || '9567');
    mockServer = await startMockLlmServer(mockPort);
    llmEndpoint = `http://${backendHost}:${mockPort}/v1/chat/completions`;
  }

  const backendEnv = {
    ...process.env,
    PYTHONPATH: '..',
    ENABLE_LLM: '1',
    ALMA_FORM_URL: formUrl,
  };

  if (llmEndpoint) {
    backendEnv.LLM_ENDPOINT = llmEndpoint;
    backendEnv.LLM_API_KEY = backendEnv.LLM_API_KEY || 'mock-key';
    backendEnv.LLM_MODEL = backendEnv.LLM_MODEL || 'mock-llm';
  }

  const backend = spawnProcess(
    'backend',
    'python',
    ['-m', 'uvicorn', 'backend.main:app', '--host', backendHost, '--port', backendPort],
    { cwd: backendDir, env: backendEnv }
  );

  await waitForHealth();

  const frontendEnv = {
    ...process.env,
    VITE_API_BASE: apiBase,
  };

  const frontend = spawnProcess(
    'frontend',
    'npm',
    ['run', 'dev', '--', '--host', frontendHost, '--port', frontendPort],
    { cwd: frontendDir, env: frontendEnv }
  );

  const shutdown = () => {
    backend.kill('SIGTERM');
    frontend.kill('SIGTERM');
    if (mockServer) {
      mockServer.close();
    }
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  console.log('[e2e] Backend + frontend ready.');
  await new Promise(() => {});
}

main().catch((error) => {
  console.error('[e2e] Failed to start servers', error);
  process.exit(1);
});

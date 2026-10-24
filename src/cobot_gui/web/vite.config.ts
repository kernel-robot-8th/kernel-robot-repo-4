import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import fs from 'fs'
import type { IncomingMessage, ServerResponse } from 'http'
import type { ViteDevServer } from 'vite'

type FeedbackRecord = Record<string, unknown>

function feedbackApiPlugin() {
  const dataDir = path.resolve(__dirname, './src/data')
  const dataFile = path.join(dataDir, 'fms_feedback.json')

  function ensureFile() {
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true })
    }
    if (!fs.existsSync(dataFile)) {
      fs.writeFileSync(dataFile, '[]', 'utf-8')
    }
  }

  function readData(): FeedbackRecord[] {
    ensureFile()
    try {
      const raw = fs.readFileSync(dataFile, 'utf-8')
      return JSON.parse(raw) as FeedbackRecord[]
    } catch {
      return []
    }
  }

  function writeData(data: unknown) {
    ensureFile()
    fs.writeFileSync(dataFile, JSON.stringify(data, null, 2), 'utf-8')
  }

  return {
    name: 'fms-feedback-api',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/api/feedback', (req: IncomingMessage, res: ServerResponse, next: () => void) => {
        const url = new URL(req.url || '', `http://${req.headers.host || 'localhost'}`)

        if (req.method === 'GET') {
          const list = readData()
          const menuId = url.searchParams.get('menuId')
          const result = menuId ? list.filter((item) => item.menuId === menuId) : list
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.statusCode = 200
          res.end(JSON.stringify(result))
          return
        }

        if (req.method === 'POST') {
          let body = ''
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString()
          })
          req.on('end', () => {
            try {
              const item = JSON.parse(body) as FeedbackRecord
              if (!item.content || !item.menuId) {
                res.statusCode = 400
                res.setHeader('Content-Type', 'application/json; charset=utf-8')
                res.end(JSON.stringify({ error: 'menuId and content are required' }))
                return
              }
              const list = readData()
              const newItem = {
                id: item.id || `fb-${Date.now()}`,
                menuId: item.menuId,
                menuName: item.menuName || item.menuId,
                author: item.author || '익명',
                category: item.category || 'suggestion',
                content: item.content,
                createdAt: item.createdAt || new Date().toISOString(),
              }
              const updated = [newItem, ...list.filter((x) => x.id !== newItem.id)]
              writeData(updated)
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.statusCode = 201
              res.end(JSON.stringify({ success: true, item: newItem, total: updated.length }))
            } catch (err) {
              res.statusCode = 500
              res.setHeader('Content-Type', 'application/json; charset=utf-8')
              res.end(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }))
            }
          })
          return
        }

        if (req.method === 'DELETE') {
          const id = url.pathname.replace(/^\//, '') || url.searchParams.get('id')
          if (!id) {
            res.statusCode = 400
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(JSON.stringify({ error: 'id is required' }))
            return
          }
          const list = readData()
          const updated = list.filter((item) => item.id !== id)
          writeData(updated)
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.statusCode = 200
          res.end(JSON.stringify({ success: true, deletedId: id, total: updated.length }))
          return
        }

        next()
      })
    },
  }
}

// 개발 서버의 /api 는 게이트웨이(S2)로 넘긴다. 게이트웨이가 없으면 VITE_DATA=mock (기본) 으로 쓴다.
export default defineConfig({
  plugins: [react(), tailwindcss(), feedbackApiPlugin()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '^/api/(?!feedback).*': process.env.VITE_GATEWAY_URL ?? 'http://127.0.0.1:8080',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})

# AI 理財顧問系統

雲端系統期末專題（第八組）。使用者提出投資問題後，系統分派給三位不同風格的 AI 顧問。每位顧問是一個獨立容器，執行不同的本地 LLM（Ollama）。顧問回傳結構化的買賣建議，使用者可以決定採納或跳過，系統會模擬下單並追蹤各顧問的績效。

## 架構

```
            +--------------------------------------------+
 browser -> | manager  (Flask, :5000)                    |
            |   dispatcher      queue / dispatch / retry |
            |   health_monitor  heartbeat (/ping)        |
            |   price_updater   periodic price ticks     |
            |   /shared         jobs, holdings, prices   |
            +------+--------------+--------------+-------+
        /exec      |              |              |      ^  /api/internal/done
                   v              v              v      |  /api/internal/failed
            +------------+ +------------+ +------------+
            | worker1    | | worker2    | | worker3    |
            | qwen2.5    | | llama3.2   | | gemma2     |
            | :6001      | | :6002      | | :6003      |
            +------------+ +------------+ +------------+
                    each worker = Ollama + Flask API
```

manager 負責派工、心跳偵測、逾時重試與定期更新股價；共用狀態以 JSON 檔存在 `/shared` volume。

| 顧問 | 模型 | 風格 |
|---|---|---|
| 穩健哥（`advisor_qwen`） | `qwen2.5:1.5b` | 保守型：保本、配息、至少保留 30% 現金 |
| 中道姐（`advisor_llama`） | `llama3.2:3b` | 平衡型：跨 TW/US/KR/HK 四個市場分散配置 |
| 衝勁王（`advisor_gemma`） | `gemma2:2b` | 積極型：重押成長股，現金可低於 10% |

股票（QBIT、LUNA、NEXO、VORT、KIRO、HAON、PLEX、ZORA）都是虛構標的。每支標的對應一支真實股票，可以用 `yfinance` 取得真實漲跌幅（`real` 模式）；也可以用隨機漲跌模擬（`random` 模式，預設）。

## 快速開始

需要 Docker 與 Docker Compose。模型只在 CPU 上執行，第一次啟動時會自動下載模型，需要一些時間。

```bash
docker compose up -d --build

# 若模型沒有自動下載
bash scripts/pull_models.sh

# 重設展示資料（股價、持倉、工作清單）
docker exec manager python setup_demo.py
```

啟動後開啟 <http://localhost:5000>。

## 主要 API

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/api/consult` | 提出問題；`mode: "single"` 指定一位顧問，`"fanout"` 同時問三位 |
| GET | `/api/jobs` | 工作清單（可用 `status` / `advisor` / `group` 篩選） |
| DELETE | `/api/jobs/<id>` | 取消排隊中的工作 |
| POST | `/api/decision` | 對某筆建議 `accept` / `reject`，採納即模擬下單 |
| GET | `/api/portfolio` | 現金、持倉與已實現交易 |
| POST | `/api/sell` | 手動賣出持倉 |
| GET | `/api/workers` | 各 worker 狀態與 CPU / RAM |
| POST | `/api/workers/<id>/disable` · `/enable` | 停用或啟用 worker（停用時執行中的工作會重新排隊） |
| GET | `/api/advisors` | 顧問績效排行（損益、勝率、採納率、格式遵循率） |
| POST | `/api/admin/tick_price` | 手動觸發一次股價更新 |

## 工作狀態流程

```
QUEUED ──派工──▶ RUNNING ──回傳成功──▶ RESPONDED ──全部決策──▶ ACCEPTED / REJECTED
   ▲               │  └──解析失敗──▶ RESPONDED_NO_REC      └──超過決策期限──▶ EXPIRED
   │               │
   └──逾時 / worker 失聯 / 推論失敗（未超過重試上限）
                   └──超過 MAX_RETRY──▶ FAILED
QUEUED ──使用者取消──▶ CANCELLED
```

## 設定（`docker-compose.yml` 環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `PRICE_UPDATE_MINUTES` | 5 | 自動更新股價的間隔 |
| `MAX_RETRY` | 2 | 工作失敗的最大重試次數 |
| `MAX_QUEUE_PER_WORKER` | 1 | 每個 worker 同時執行的工作數 |
| `JOB_TIMEOUT_SECONDS` | 700 | 執行中工作的逾時秒數 |
| `DECISION_TIMEOUT_SECONDS` | 600 | 使用者決策期限 |
| `MAX_TOKENS` | 800 | LLM 最大輸出 token 數 |

## 目錄結構

```
manager/            Flask 管理端
  core/             dispatcher、health_monitor、price_updater、parser、rag、trade、performance
  routes/           consult、portfolio、workers、internal（worker 回呼）
  templates/        前端頁面 index.html
worker/             Ollama + Flask worker（/exec、/cancel、/ping、/stats）
shared_init/        初始股價、持倉、標的資料
scripts/            模型下載與重設腳本
雲端系統期末報告.pptx
```

## 版本與修正

- `original` 分支：原始繳交版本。
- `main` 分支：修正控制流程與併發問題（差異見 [original...main](https://github.com/AlexTsai2004/ai-advisor-system/compare/original...main)），主要包括：
  - `jobs.json` 的讀取、修改、寫回改為持鎖進行，避免 dispatcher 覆蓋 worker 的回傳結果或使用者的取消。
  - 修正 health monitor 與 dispatcher 取鎖順序相反造成的死結。
  - 忽略過時的 worker 回呼（工作已逾時重排或改派給別的 worker）。
  - `failed` 回呼確實釋放 worker；預算上限不再超出現金；部分賣出會保留剩餘股數。
  - 過期的建議不能再下單；`hold` 建議可以採納；前端跳脫 LLM 輸出。

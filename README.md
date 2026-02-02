# SPP Auto-Reply System for GMB Gorilla

AI-powered draft response generator for Service Provider Pro orders and tickets.

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  1. POLLER (runs hourly)                                    │
│     - Checks SPP for orders/tickets needing reply           │
│     - Identifies where last message was from client         │
│     - Generates draft responses via Claude API              │
│     - Saves drafts to Supabase queue                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. APPROVAL UI (web interface)                             │
│     - View pending drafts                                   │
│     - Edit responses if needed                              │
│     - Approve / Reject / Approve & Send                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. SENDER                                                  │
│     - Posts approved messages back to SPP                   │
│     - Sends as the assigned manager                         │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone and Install

```bash
cd spp-auto-reply
pip install -r requirements.txt
```

### 2. Set Up Supabase

1. Create a new Supabase project at https://supabase.com
2. Go to SQL Editor and run the contents of `supabase_schema.sql`
3. Copy your project URL and anon key

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual keys
```

Required environment variables:
- `SPP_API_KEY` - Your Service Provider Pro API key
- `ANTHROPIC_API_KEY` - Your Anthropic API key
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_KEY` - Your Supabase anon key

### 4. Test the Connection

```bash
# Test SPP connection
python spp_client.py

# Test draft generator
python draft_generator.py

# Test database
python database.py
```

### 5. Run the Poller

```bash
# Dry run - see what would be generated without saving
python poller.py --dry-run --hours 48

# Real run - generate and save drafts
python poller.py --hours 24
```

### 6. Launch Approval UI

```bash
python approval_server.py
# Open http://localhost:8000
```

## Scheduled Polling

Set up a cron job to run the poller hourly during business hours:

```bash
# Edit crontab
crontab -e

# Add this line (runs hourly 9am-5pm Mon-Fri EST)
0 9-17 * * 1-5 cd /path/to/spp-auto-reply && /usr/bin/python3 poller.py >> /var/log/spp-poller.log 2>&1
```

Or use a service like:
- **Railway** - Deploy the poller as a cron service
- **Render** - Use their cron job feature
- **AWS Lambda** - Scheduled via CloudWatch Events

## File Structure

```
spp-auto-reply/
├── spp_client.py        # SPP API client
├── draft_generator.py   # Claude API draft generation
├── database.py          # Supabase client
├── poller.py            # Main orchestration script
├── approval_server.py   # FastAPI web UI
├── supabase_schema.sql  # Database setup
├── requirements.txt     # Python dependencies
├── .env.example         # Environment template
└── README.md            # This file
```

## API Endpoints

The approval server exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/drafts` | GET | List pending drafts |
| `/api/drafts/{id}` | GET | Get specific draft |
| `/api/drafts/{id}/approve` | POST | Approve a draft |
| `/api/drafts/{id}/approve-and-send` | POST | Approve and send immediately |
| `/api/drafts/{id}/reject` | POST | Reject a draft |
| `/api/stats` | GET | Queue statistics |
| `/api/send-approved` | POST | Send all approved drafts |

## Customization

### Tone & Voice

Edit the `SYSTEM_PROMPT` in `draft_generator.py` to adjust:
- Greeting style
- Response length
- Brand voice
- Common scenarios

### Confidence Levels

The system assigns confidence levels to drafts:
- **High** - Simple, straightforward responses
- **Medium** - Longer responses that may need review
- **Low** - Complex situations, uncertainty, or escalation needed

You can auto-approve high-confidence drafts by enabling the setting in Supabase.

### Service Stages

The generator is aware of GMB Gorilla service stages:
- Onboarding (Days 1-7)
- Audit (Days 8-15)
- Enhancement (Days 16-23)
- Management (Days 24-30+)

It uses the order status to provide stage-appropriate responses.

## Troubleshooting

### "No items needing reply"
- Check that orders/tickets have recent activity (within lookback window)
- Verify the last message is from the client (not staff)
- Check for closed/completed status filtering

### Draft generation fails
- Verify your Anthropic API key is valid
- Check the conversation history isn't empty
- Look at the error logs in `poller_runs` table

### Sending fails
- Verify the manager_user_id is set and valid
- Check the SPP API response in `spp_response` column
- Ensure the order/ticket still exists

## Cost Estimates

**Claude API (Sonnet):**
- ~500 tokens per draft (input + output)
- ~$0.003 per draft at current pricing
- 100 drafts/day ≈ $0.30/day ≈ $9/month

**Supabase:**
- Free tier handles this easily
- ~1MB/month in storage for logs

## Support

Questions? Check the poller run logs in Supabase:
```sql
SELECT * FROM poller_runs ORDER BY started_at DESC LIMIT 10;
```

Or view processed messages:
```sql
SELECT * FROM processed_messages WHERE action = 'error' ORDER BY created_at DESC;
```

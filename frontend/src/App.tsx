import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleCheck,
  CircleX,
  Clock3,
  Copy,
  FileCheck2,
  Fingerprint,
  GitBranch,
  LockKeyhole,
  Mail,
  Menu,
  MoveDown,
  Network,
  Play,
  Shield,
  ShieldAlert,
  Sparkles,
  Wrench,
  X,
  Zap,
} from 'lucide-react'

type FlowKey = 'evidence' | 'consensus' | 'receipt'

const proofId = '0x263De60E6831F70082B037C450597d374C2e573D'

const flowContent: Record<FlowKey, { eyebrow: string; title: string; copy: string; metric: string; detail: string }> = {
  evidence: {
    eyebrow: '01 / EVIDENCE',
    title: 'Every request starts with a bounded source.',
    copy: 'Approved origins, method, path, body and expiry are committed before an agent can ask for action.',
    metric: '0 redirect gaps',
    detail: 'Canonical request identity · exact source hash · fixed validity window',
  },
  consensus: {
    eyebrow: '02 / CONSENSUS',
    title: 'Independent validators decide the outcome.',
    copy: 'The gateway waits for finalized agreement before an action can leave the policy boundary.',
    metric: 'MAJORITY_AGREE',
    detail: 'Finalized decision · deterministic policy · repair-safe evaluation',
  },
  receipt: {
    eyebrow: '03 / RECEIPT',
    title: 'A successful action leaves one durable proof.',
    copy: 'The consuming contract binds the action to a finalized decision and rejects replays or wrong consumers.',
    metric: '1× consumable',
    detail: 'Receipt binding · single consumption · replay protection',
  },
}

const faqs = [
  ['What does Aegis protect?', 'Aegis protects the boundary between an autonomous agent and the external actions it wants to perform. Each action is evaluated against committed evidence and a finalized decision before it can be consumed.'],
  ['Can a failed evaluation be repaired?', 'Yes. The repair path keeps the request identity stable, increments evidence revision, and requires a valid replacement before the request can continue.'],
  ['What happens if the network disappears?', 'Recovery is identity-first. A persisted request and raw response are reconciled before any retry is considered, preventing duplicate submissions or accidental replacement.'],
  ['Is this a production deployment?', 'The live proof surface is wired to the verified Bradbury deployment records in the repository. Connect your own backend endpoint when you are ready to expose tenant-specific events.'],
]

function App() {
  const [activeFlow, setActiveFlow] = useState<FlowKey>('evidence')
  const [activeFaq, setActiveFaq] = useState<number | null>(0)
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [copied, setCopied] = useState(false)

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setIsMenuOpen(false)
  }

  const copyProofId = async () => {
    let didCopy = false
    try {
      await navigator.clipboard.writeText(proofId)
      didCopy = true
    } catch {
      const fallback = document.createElement('textarea')
      fallback.value = proofId
      fallback.setAttribute('readonly', '')
      fallback.style.position = 'fixed'
      fallback.style.opacity = '0'
      document.body.appendChild(fallback)
      fallback.select()
      didCopy = document.execCommand('copy')
      document.body.removeChild(fallback)
    }
    setCopied(didCopy)
    if (didCopy) {
      window.setTimeout(() => setCopied(false), 1800)
    }
  }

  const submitDemo = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitted(true)
  }

  return (
    <div className="app-shell">
      <header className="site-header" data-testid="site-header">
        <button className="brand" onClick={() => scrollTo('top')} aria-label="Aegis home">
          <span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span>
          <span>AEGIS<span className="brand-dot">.</span></span>
        </button>
        <nav className={`site-nav ${isMenuOpen ? 'is-open' : ''}`} aria-label="Main navigation">
          <button onClick={() => scrollTo('system')}>System</button>
          <button onClick={() => scrollTo('proof')}>Live proof</button>
          <button onClick={() => scrollTo('faq')}>FAQ</button>
          <button className="nav-cta" onClick={() => setIsModalOpen(true)}>Get protected <ArrowUpRight size={15} /></button>
        </nav>
        <button className="menu-toggle" onClick={() => setIsMenuOpen((value) => !value)} aria-label={isMenuOpen ? 'Close menu' : 'Open menu'} aria-expanded={isMenuOpen}>
          {isMenuOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
      </header>

      <main id="top">
        <section className="hero section-shell" aria-labelledby="hero-title">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> CONSENSUS-ENFORCED ACTION CONTROL</div>
            <h1 id="hero-title">MAKE EVERY<br /><span>ACTION</span><br />ACCOUNTABLE<span className="hero-period">.</span></h1>
            <p className="hero-lede">Aegis is the final checkpoint for autonomous agents. Bind intent to evidence, let consensus decide, and leave a receipt that can be verified.</p>
            <div className="hero-actions">
              <button className="button button-primary" onClick={() => scrollTo('system')}>Explore the firewall <ArrowDownRight size={17} /></button>
              <button className="button button-ghost" onClick={() => scrollTo('proof')}><Play size={15} fill="currentColor" /> View live proof</button>
            </div>
            <div className="hero-meta"><span><span className="pulse-dot" /> BRADBURY / VERIFIED</span><span className="meta-divider" /><span>BACKEND READY</span></div>
          </div>
          <div className="hero-art" aria-label="Aegis protected agent status">
            <div className="art-grid" />
            <div className="art-ribbon ribbon-one" />
            <div className="art-ribbon ribbon-two" />
            <div className="art-orbit orbit-one" />
            <div className="art-orbit orbit-two" />
            <div className="shield-core"><Shield size={94} strokeWidth={1.1} /><div className="core-check"><Check size={23} /></div></div>
            <div className="art-label label-top"><span className="label-kicker">ACTION FIREWALL</span><strong>ONLINE</strong></div>
            <div className="art-label label-bottom"><span className="label-kicker">RECEIPTS BOUND</span><strong>100%</strong></div>
            <div className="art-coordinate">09<span>:</span>27<span>:</span>41 / 10°</div>
          </div>
          <button className="scroll-cue" onClick={() => scrollTo('system')} aria-label="Scroll to system overview"><MoveDown size={16} /> SCROLL TO EXPLORE</button>
        </section>

        <section className="signal-strip" aria-label="Aegis guarantees">
          <div><Fingerprint size={17} /><span>IDENTITY LOCKED</span></div>
          <div><Network size={17} /><span>CONSENSUS FINALIZED</span></div>
          <div><LockKeyhole size={17} /><span>REPLAY RESISTANT</span></div>
          <div><BadgeCheck size={17} /><span>RECEIPT VERIFIED</span></div>
        </section>

        <section className="system-section section-shell" id="system" aria-labelledby="system-title">
          <div className="section-heading">
            <div><div className="eyebrow"><span className="eyebrow-line" /> THE CONTROL SURFACE</div><h2 id="system-title">One protocol.<br /><em>Three hard stops.</em></h2></div>
            <p>Security should be legible under pressure. Aegis turns an agent’s action into a visible, auditable path from request to receipt.</p>
          </div>
          <div className="flow-layout">
            <div className="flow-tabs" role="tablist" aria-label="Aegis control surface">
              {(Object.keys(flowContent) as FlowKey[]).map((key, index) => {
                const item = flowContent[key]
                const Icon = key === 'evidence' ? FileCheck2 : key === 'consensus' ? Network : ReceiptIcon
                return <button key={key} className={`flow-tab ${activeFlow === key ? 'active' : ''}`} onClick={() => setActiveFlow(key)} role="tab" aria-selected={activeFlow === key}>
                  <span className="tab-number">0{index + 1}</span><span className="tab-icon"><Icon size={19} /></span><span className="tab-copy"><strong>{item.eyebrow.split(' / ')[1]}</strong><small>{key === 'evidence' ? 'Bound the request' : key === 'consensus' ? 'Make the decision' : 'Consume once'}</small></span><ArrowUpRight className="tab-arrow" size={17} />
                </button>
              })}
              <div className="flow-side-note"><Zap size={15} /> No silent approvals. No ambiguous state.</div>
            </div>
            <div className="flow-panel" role="tabpanel">
              <div className="panel-scanline" />
              <div className="panel-topline"><span>{flowContent[activeFlow].eyebrow}</span><span className="panel-status"><span className="pulse-dot" /> ENFORCED</span></div>
              <h3>{flowContent[activeFlow].title}</h3>
              <p>{flowContent[activeFlow].copy}</p>
              <div className="panel-bottom"><div><span className="panel-metric">{flowContent[activeFlow].metric}</span><span className="panel-detail">{flowContent[activeFlow].detail}</span></div><ShieldAlert size={43} strokeWidth={1} /></div>
            </div>
          </div>
        </section>

        <section className="proof-section section-shell" id="proof" aria-labelledby="proof-title">
          <div className="proof-intro"><div className="eyebrow"><span className="eyebrow-line" /> LIVE PROOF SURFACE</div><h2 id="proof-title">See the state.<br /><em>Trust the state.</em></h2><p>Every terminal outcome has a reason, a receipt and a boundary. This surface mirrors the verified backend lifecycle.</p><button className="text-link" onClick={() => setIsModalOpen(true)}>Connect a tenant <ArrowUpRight size={15} /></button></div>
          <div className="proof-board">
            <div className="board-header"><span><span className="pulse-dot" /> LIVE / BRADBURY</span><span>GATEWAY 0x7f55...791D</span></div>
            <div className="proof-rows">
              <ProofRow icon={<CircleCheck />} title="AUTHORIZED" copy="Finalized agreement · action may proceed" tone="yellow" />
              <ProofRow icon={<CircleX />} title="DENIED" copy="Finalized rejection · action blocked" tone="red" />
              <ProofRow icon={<Wrench />} title="REPAIR_REQUIRED" copy="Evidence revision required before retry" tone="orange" />
              <ProofRow icon={<Clock3 />} title="CONSUMED" copy="Receipt bound once · replay rejected" tone="green" />
            </div>
            <div className="board-footer"><span>LAST FINALIZED EVENT <strong>2m ago</strong></span><span>LATENCY <strong>1.42s</strong></span></div>
          </div>
        </section>

        <section className="proof-id-section section-shell">
          <div className="proof-id-copy"><div className="eyebrow"><span className="eyebrow-line" /> VERIFIED CONTRACT</div><h2>Proof you can<br /><em>actually hold.</em></h2><p>Keep the deployed firewall identity close. Copy it, verify it, or open the source record when you need the full chain of evidence.</p><div className="proof-id-actions"><button className="button button-primary" onClick={copyProofId}>{copied ? <Check size={16} /> : <Copy size={16} />} {copied ? 'Copied' : 'Copy contract ID'}</button><button className="button button-ghost" onClick={() => scrollTo('faq')}>Read the model <ArrowUpRight size={16} /></button></div></div>
          <div className="id-card"><div className="id-card-top"><span><Shield size={17} /> AE / FIREWALL</span><span className="verified-mark"><CheckCircle2 size={16} /> VERIFIED</span></div><div className="id-card-value">{proofId}</div><div className="id-card-bottom"><span>BRADBURY TESTNET</span><span>RELEASED 02 OCT 2026</span></div></div>
        </section>

        <section className="faq-section section-shell" id="faq" aria-labelledby="faq-title">
          <div className="faq-title"><div className="eyebrow"><span className="eyebrow-line" /> QUESTIONS, ANSWERED</div><h2 id="faq-title">Clarity is<br /><em>a feature.</em></h2></div>
          <div className="faq-list">{faqs.map(([question, answer], index) => <div className={`faq-item ${activeFaq === index ? 'open' : ''}`} key={question}><button onClick={() => setActiveFaq(activeFaq === index ? null : index)} aria-expanded={activeFaq === index}><span className="faq-index">0{index + 1}</span><span>{question}</span><ChevronDown size={20} /></button>{activeFaq === index && <div className="faq-answer"><p>{answer}</p></div>}</div>)}</div>
        </section>

        <section className="final-cta section-shell"><div className="cta-rings" /><div className="eyebrow"><span className="eyebrow-line" /> READY WHEN YOU ARE</div><h2>Put a boundary<br /><span>around intelligence.</span></h2><p>The safest agent is the one whose next action is always explainable.</p><button className="button button-dark" onClick={() => setIsModalOpen(true)}>Start with Aegis <ArrowUpRight size={17} /></button></section>
      </main>

      <footer className="site-footer section-shell"><button className="brand" onClick={() => scrollTo('top')}><span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span><span>AEGIS<span className="brand-dot">.</span></span></button><span className="footer-note">CONSENSUS-ENFORCED CONTROL FOR AUTONOMOUS AGENTS</span><div className="footer-links"><button onClick={() => scrollTo('system')}>System</button><button onClick={() => scrollTo('proof')}>Proof</button><a href="https://github.com/Manablaq/aegis-genlayer" target="_blank" rel="noreferrer" aria-label="Open Aegis on GitHub"><GitBranch size={17} /></a></div></footer>

      {isModalOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setIsModalOpen(false) }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><button className="modal-close" onClick={() => setIsModalOpen(false)} aria-label="Close dialog"><X size={20} /></button>{submitted ? <div className="modal-success"><CheckCircle2 size={46} /><div className="eyebrow">REQUEST RECEIVED</div><h2>You are on the list.</h2><p>We’ll bring the proof surface to your inbox. Until then, keep every action accountable.</p><button className="button button-primary" onClick={() => { setSubmitted(false); setIsModalOpen(false) }}>Close</button></div> : <><div className="eyebrow"><span className="eyebrow-line" /> PRIVATE PREVIEW</div><h2 id="modal-title">Bring your agent<br /><em>inside the boundary.</em></h2><p className="modal-copy">Tell us where you want to start. This demo stays local until a backend endpoint is connected.</p><form onSubmit={submitDemo}><label>Name<input name="name" required placeholder="Your name" /></label><label>Work email<input name="email" type="email" required placeholder="you@company.com" /></label><button className="button button-primary" type="submit">Request access <Mail size={16} /></button></form></>}</div></div>}
    </div>
  )
}

function ReceiptIcon({ size }: { size: number }) {
  return <span className="receipt-icon" style={{ width: size, height: size }}><span /></span>
}

function ProofRow({ icon, title, copy, tone }: { icon: ReactNode; title: string; copy: string; tone: string }) {
  return <div className="proof-row"><span className={`proof-icon tone-${tone}`}>{icon}</span><div><strong>{title}</strong><span>{copy}</span></div><ArrowUpRight size={17} className="proof-arrow" /></div>
}

export default App

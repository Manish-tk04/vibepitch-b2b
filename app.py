import streamlit as st
import google.generativeai as genai
import os
import pandas as pd
import time
import requests
import base64
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import pdfplumber

# Must be FIRST Streamlit command
st.set_page_config(page_title="VibePitch B2B", layout="wide", page_icon="⚡")

# ──────────────────────────────────────────────
# 1. API KEY
# ──────────────────────────────────────────────
api_key = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass
if not api_key:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("🚨 API Key not found. Add GEMINI_API_KEY to Streamlit Secrets or .env file.")
    st.stop()

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-2.5-flash')

# ──────────────────────────────────────────────
# 2. USER AUTH — reads from users.txt on GitHub
# ──────────────────────────────────────────────

USERS_FILE = "users.txt"

def load_users() -> dict:
    """Load users from local users.txt. Returns {email: {password, plan}}"""
    users = {}
    if not os.path.exists(USERS_FILE):
        return users
    with open(USERS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 3:
                email, password, plan = parts[0].strip().lower(), parts[1].strip(), parts[2].strip()
                users[email] = {"password": password, "plan": plan}
    return users

def check_login(email: str, password: str) -> dict | None:
    users = load_users()
    st.write("DEBUG users loaded:", users)  # temporary debug
    user = users.get(email.lower().strip())
    if user and user["password"] == password.strip():
        return user
    return None

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_plan" not in st.session_state:
    st.session_state.user_plan = None

if not st.session_state.authenticated:
    st.markdown("""
        <div style='text-align:center; padding: 60px 0 20px 0;'>
            <h1>⚡ VibePitch</h1>
            <p style='color: gray;'>AI-Powered Sponsorship Outreach</p>
        </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        login_email = st.text_input("Email Address", placeholder="you@gmail.com")
        login_pass  = st.text_input("Access Password", type="password", placeholder="VIBE-XXXX-XXXX")
        if st.button("Enter", use_container_width=True, type="primary"):
            user = check_login(login_email, login_pass)
            if user:
                st.session_state.authenticated = True
                st.session_state.user_plan     = user["plan"]
                st.rerun()
            else:
                st.error("Invalid email or password. Contact support if you need help.")
        st.caption("Don't have access? [Get started](https://manish-tk04.github.io/vibepitch-b2b/#pricing)")
    st.stop()

# ──────────────────────────────────────────────
# 3. SESSION STATE
# ──────────────────────────────────────────────
st.title("⚡ VibePitch: AI Sponsorship Automator")

for key, default in [
    ("single_email_body", None),
    ("single_email_subject", None),
    ("bulk_data", None),
    ("brand_research_cache", {}),
    ("user_templates", {}),
    ("sponsorship_tiers", []),
    ("brochure_text", ""),
    ("discovered_brands", []),
    ("show_preview_single", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default
if st.session_state.brand_research_cache is None:
    st.session_state.brand_research_cache = {}

# ──────────────────────────────────────────────
# 4. BUILT-IN TEMPLATES
# ──────────────────────────────────────────────
BUILTIN_TEMPLATES = {
    "🍔 F&B / Food & Beverage": """STRUCTURE:
- Hook: Reference their product category and the event's food/lifestyle audience
- Problem: Brands in F&B struggle to get direct access to young consumers in real, offline settings
- Solution: Our event gives them a live sampling/activation opportunity at scale
- Proof: Mention footfall and demographics
- CTA: Invite them for a 15-min call to discuss a custom food court activation""",

    "💻 Tech / Startup": """STRUCTURE:
- Hook: Connect their product to the tech-savvy, student/young-professional crowd at the event
- Problem: Digital ads are noisy — brand recall is low. Live events create real impressions
- Solution: Hackathons, gaming zones, or demo booths at our event create direct product trials
- Proof: Footfall + audience profile (engineers, developers, startup enthusiasts)
- CTA: Offer to share a detailed sponsorship deck for their review""",

    "👗 Fashion / Lifestyle": """STRUCTURE:
- Hook: Tie their brand identity to the cultural energy and aesthetic of the event
- Problem: Fashion brands need authentic moments with their target demographic, not just ad impressions
- Solution: Live brand activations, photo ops, and merchandise integrations at a high-energy event
- Proof: Expected footfall and social media amplification opportunity
- CTA: Ask if they'd be open to a quick 10-min exploratory chat""",

    "💳 Fintech / BFSI": """STRUCTURE:
- Hook: Reference their focus on reaching young, first-time earners or students
- Problem: Fintech brands find it hard to build trust with Gen Z through digital channels alone
- Solution: Sponsoring an event creates credibility and direct sign-up opportunities on the ground
- Proof: Footfall numbers and audience age/income profile
- CTA: Propose a co-branded activation and ask for a brief call""",

    "🎓 EdTech / Online Learning": """STRUCTURE:
- Hook: Connect their mission of accessible education to the aspirational student audience at the event
- Problem: EdTech CAC is high through digital ads — live events deliver warm, high-intent leads
- Solution: A stall, quiz activation, or free-trial giveaway at the event builds pipeline directly
- Proof: Audience profile — students actively seeking career and skill development
- CTA: Share the deck and request a quick discovery call""",
}

# ──────────────────────────────────────────────
# 5. CORE FUNCTIONS
# ──────────────────────────────────────────────

def scrape_website(url: str) -> str:
    if not url or not url.startswith("http"):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; VibePitchBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        priority_tags = soup.find_all(["h1", "h2", "h3", "p", "li"])
        text = " ".join(t.get_text(separator=" ", strip=True) for t in priority_tags)
        return text[:3000]
    except Exception:
        return ""


def research_brand(brand_name: str, brand_url: str) -> str:
    cache_key = f"{brand_name}_{brand_url}"
    if cache_key in st.session_state.brand_research_cache:
        return st.session_state.brand_research_cache[cache_key]
    scraped_text = scrape_website(brand_url)
    prompt = f"""You are a brand intelligence analyst preparing a sponsorship targeting brief.
Brand Name: {brand_name}
Website URL: {brand_url}
Scraped Homepage Content:
\"\"\"{scraped_text if scraped_text else "No content scraped. Use your knowledge of this brand."}\"\"\"

Produce a concise brand intelligence brief covering:
1. CORE BUSINESS: What does this company do? Who is their customer?
2. BRAND PERSONALITY: What tone/values does their marketing reflect?
3. TARGET AUDIENCE: Demographics and psychographics.
4. MARKETING GOALS: What would motivate them to sponsor an event?
5. SPONSORSHIP FIT ANGLE: One sharp specific reason why this brand benefits from sponsoring an event.
6. ESTIMATED BUDGET RANGE: Rough estimate of sponsorship amount this brand could afford (e.g. 50K-2L, 2L-10L, 10L+)

Be factual and specific. No fluff. Max 220 words."""
    try:
        research = model.generate_content(prompt).text.strip()
    except Exception as e:
        research = f"Brand research unavailable: {e}"
    st.session_state.brand_research_cache[cache_key] = research
    return research


def extract_brochure_tiers(brochure_text: str) -> list:
    prompt = f"""You are analyzing a sponsorship brochure for an event.

BROCHURE TEXT:
\"\"\"{brochure_text[:5000]}\"\"\"

Extract all sponsorship tiers mentioned. Output a JSON array:
[
  {{
    "tier_name": "Title Sponsor",
    "price": "5,00,000",
    "benefits": ["Logo on all banners", "Stage naming rights"],
    "best_for": "Large national brands with high marketing budgets"
  }}
]

If no tiers found, return [].
Output ONLY valid JSON. No explanation, no markdown backticks."""
    try:
        response = model.generate_content(prompt).text.strip()
        response = response.replace("```json", "").replace("```", "").strip()
        return json.loads(response)
    except Exception:
        return []


def suggest_tier_for_brand(brand_profile: str, tiers: list) -> str:
    if not tiers:
        return ""
    tiers_text = "\n".join([
        f"- {t['tier_name']} ({t.get('price','N/A')}): {', '.join(t.get('benefits', []))}"
        for t in tiers
    ])
    prompt = f"""Based on this brand intelligence profile:
{brand_profile}

And these available sponsorship tiers:
{tiers_text}

Which single tier is the BEST fit for this brand? Consider their budget range, marketing goals, and which benefits align.
Respond in 2-3 sentences max. Be direct. Name the tier and briefly explain why."""
    try:
        return model.generate_content(prompt).text.strip()
    except Exception:
        return ""


def generate_pitch(b_name, b_url, b_vibe, custom_ctx="None",
                   activations=[], brand_profile="", template="",
                   tier_suggestion="") -> tuple:

    tier_section = f"""
RECOMMENDED SPONSORSHIP TIER FOR THIS BRAND:
{tier_suggestion}
Naturally reference this tier in the email as a tailored suggestion.
""" if tier_suggestion else ""

    template_section = f"""
EMAIL STRUCTURE TO FOLLOW (use as skeleton, rewrite all content with brand research):
{template}
""" if template else ""

    prompt = f"""You are an elite B2B sponsorship sales copywriter.

YOUR ROLE:
- SENDER: You represent {event_name or "[Event Name]"}.
- RECIPIENT: Writing TO the marketing/partnerships team at {b_name}.

EVENT DETAILS:
- Dates: {start_date} to {end_date}
- Expected Footfall: {footfall:,}
- Sponsorship Deck: {deck_url if deck_url else "Available on request"}
- Requested Activations: {', '.join(activations) if activations else 'Suggest one logical brand activation.'}
- Additional Context: {custom_ctx if custom_ctx else 'None'}

BRAND INTELLIGENCE BRIEF:
{brand_profile if brand_profile else "No profile available — write a general but compelling pitch."}

TONE: {b_vibe}
{tier_section}
{template_section}
WRITING RULES:
1. Open with a hook referencing something SPECIFIC about {b_name}. No generic openers like "Hope this finds you well" or "I wanted to reach out".
2. Connect {b_name}'s marketing goals to THIS event's audience with specific reasoning.
3. LENGTH: Write 3 solid paragraphs. Not a one-liner, not an essay. First paragraph = hook + why them. Second paragraph = what the event offers + audience fit. Third paragraph = specific activation idea + CTA.
4. FORMATTING: Plain text ONLY. No asterisks, no bold, no bullet points, no markdown of any kind. This is an email, not a document.
5. Subject line must be specific, intriguing, and human — like a real salesperson wrote it. Examples of good subjects: "Your brand + 12,000 students at TechFest?", "A sponsorship idea for {b_name} — worth 5 minutes?", "How {b_name} can own the room at [Event]". NEVER write generic subjects like "Sponsorship Proposal" or "Partnership Opportunity".
6. One clear CTA at the end — specific ask, not vague. E.g. "Would you be open to a 15-minute call this week?" not "Let me know your thoughts."
7. Do NOT use placeholder text. Use the exact signature provided.
8. Do NOT write from {b_name}'s perspective. You are pitching TO them.
9. Write like a sharp, confident human — not like a corporate email template.

OUTPUT FORMAT (strictly follow):
SUBJECT: [subject line here]
BODY:
[email body here]
{sender_signature}"""

    try:
        response_text = model.generate_content(prompt).text
    except Exception as e:
        return "Error generating subject", f"Generation failed: {e}"

    if "BODY:" in response_text:
        parts = response_text.split("BODY:", 1)
        sub  = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
    else:
        sub  = "Sponsorship Proposal"
        body = response_text

    # Strip any accidental SUBJECT line leaked into body
    if body.upper().startswith("SUBJECT:"):
        body = "\n".join(body.split("\n")[1:]).strip()

    return sub, body


def generate_with_retry(b_name, b_url, b_vibe, custom_ctx="None",
                         activations=[], brand_profile="", template="",
                         tier_suggestion="", retries=3):
    for attempt in range(retries):
        try:
            return generate_pitch(b_name, b_url, b_vibe, custom_ctx,
                                   activations, brand_profile, template, tier_suggestion)
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                time.sleep(2 ** attempt)
            else:
                return "Error", f"Failed: {e}"
    return "Error", "Max retries hit. Check your API quota."


def send_email_smtp(smtp_host, smtp_port, smtp_user, smtp_pass,
                    from_name, to_email, subject, body, attachments=None):
    try:
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_obj in attachments:
                file_obj.seek(0)
                part = MIMEBase("application", "octet-stream")
                part.set_payload(file_obj.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition",
                                f"attachment; filename={file_obj.name}")
                msg.attach(part)

        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True, f"✅ Sent to {to_email}"
    except smtplib.SMTPAuthenticationError:
        return False, "❌ Auth failed — check email/password or App Password."
    except smtplib.SMTPException as e:
        return False, f"❌ SMTP error: {e}"
    except Exception as e:
        return False, f"❌ Error: {e}"


def discover_brands(domains: list, event_context: str, num_per_domain: int = 3) -> list:
    domains_str = ", ".join(domains)
    prompt = f"""You are a sponsorship strategist. Suggest {num_per_domain} real well-known brands per domain ideal for sponsoring this event:

EVENT CONTEXT: {event_context}
DOMAINS REQUESTED: {domains_str}

For each brand output a JSON array:
[
  {{
    "brand_name": "Brand Name",
    "website": "https://...",
    "domain": "Domain it belongs to",
    "core_business": "What they do in 1 sentence",
    "target_audience": "Who their customers are",
    "brand_personality": "Their tone and values",
    "marketing_goals": "Why they would sponsor events",
    "sponsorship_fit": "Specific reason they fit THIS event",
    "estimated_budget": "Rough sponsorship budget range e.g. 1L-5L"
  }}
]

Output ONLY valid JSON. No explanation, no markdown. Suggest real brands only."""
    try:
        response = model.generate_content(prompt).text.strip()
        response = response.replace("```json", "").replace("```", "").strip()
        return json.loads(response)
    except Exception:
        return []


# ──────────────────────────────────────────────
# 6. EVENT CONFIG
# ──────────────────────────────────────────────
with st.expander("⚙️ Event & Sender Details", expanded=True):
    event_name = st.text_input("Organization & Event Name",
                                placeholder="e.g. TechFest 2025 — IIT Bombay")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("Start Date")
    with col_d2:
        end_date = st.date_input("End Date")
    col1, col2 = st.columns(2)
    with col1:
        footfall = st.number_input("Expected Footfall", min_value=0, step=500, value=0)
    with col2:
        deck_url = st.text_input("Sponsorship Deck URL", placeholder="https://...")
    sender_signature = st.text_area(
        "Your Email Signature",
        placeholder="Warm regards,\nRahul Sharma\nSponsorship Head, TechFest | +91-XXXXXXXXXX"
    )

# ──────────────────────────────────────────────
# 7. BROCHURE UPLOAD & TIER EXTRACTOR
# ──────────────────────────────────────────────
with st.expander("📄 Sponsorship Brochure & Tier Extractor"):
    st.caption("Upload your fest brochure — AI extracts sponsorship tiers automatically, then you confirm.")
    brochure_file = st.file_uploader(
        "Upload Brochure", type=["pdf", "png", "jpg", "jpeg", "txt"],
        key="brochure_upload"
    )

    if brochure_file:
        if st.button("🤖 Extract Tiers from Brochure", type="primary"):
            with st.spinner("Reading brochure and extracting tiers..."):
                file_bytes = brochure_file.read()
                if brochure_file.type == "application/pdf":
                    # Extract text locally — free Gemini key doesn't support PDF uploads
                    import io
                    text_pages = []
                    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text_pages.append(page_text)
                    st.session_state.brochure_text = "\n".join(text_pages)
                elif brochure_file.type in ["image/png", "image/jpeg", "image/jpg"]:
                    b64 = base64.b64encode(file_bytes).decode()
                    resp = genai.GenerativeModel('gemini-2.5-flash').generate_content([
                        {"mime_type": brochure_file.type, "data": b64},
                        "Extract all text from this brochure image. Return only the raw text."
                    ])
                    st.session_state.brochure_text = resp.text
                else:
                    st.session_state.brochure_text = file_bytes.decode("utf-8", errors="ignore")

                tiers = extract_brochure_tiers(st.session_state.brochure_text)
                st.session_state.sponsorship_tiers = tiers

            if st.session_state.sponsorship_tiers:
                st.success(f"✅ Extracted {len(st.session_state.sponsorship_tiers)} tiers!")
            else:
                st.warning("No tiers detected. Add them manually below.")

    if st.session_state.sponsorship_tiers:
        st.markdown("**📋 Extracted Tiers — Review & Confirm**")
        for i, tier in enumerate(st.session_state.sponsorship_tiers):
            with st.expander(f"🏆 {tier.get('tier_name', f'Tier {i+1}')} — {tier.get('price', 'N/A')}"):
                col_t1, col_t2 = st.columns(2)
                with col_t1:
                    new_name  = st.text_input("Tier Name",  value=tier.get("tier_name", ""), key=f"tname_{i}")
                    new_price = st.text_input("Price",       value=tier.get("price", ""),     key=f"tprice_{i}")
                with col_t2:
                    new_best  = st.text_input("Best For",   value=tier.get("best_for", ""),   key=f"tbest_{i}")
                new_benefits = st.text_area(
                    "Benefits (one per line)",
                    value="\n".join(tier.get("benefits", [])),
                    height=100, key=f"tbenefits_{i}"
                )
                col_ts1, col_ts2 = st.columns(2)
                with col_ts1:
                    if st.button("💾 Save Tier", key=f"tsave_{i}"):
                        st.session_state.sponsorship_tiers[i] = {
                            "tier_name": new_name, "price": new_price,
                            "best_for": new_best,
                            "benefits": [b.strip() for b in new_benefits.split("\n") if b.strip()]
                        }
                        st.success("Updated!")
                with col_ts2:
                    if st.button("🗑️ Remove Tier", key=f"tdel_{i}"):
                        st.session_state.sponsorship_tiers.pop(i)
                        st.rerun()

    st.markdown("**➕ Add Tier Manually**")
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        m_name  = st.text_input("Tier Name",  placeholder="e.g. Gold Sponsor",   key="manual_tname")
        m_price = st.text_input("Price",       placeholder="e.g. 2,00,000",       key="manual_tprice")
    with col_m2:
        m_best  = st.text_input("Best For",   placeholder="e.g. Mid-size brands", key="manual_tbest")
    m_benefits = st.text_area("Benefits (one per line)", height=80, key="manual_tbenefits")
    if st.button("➕ Add Tier"):
        if m_name:
            st.session_state.sponsorship_tiers.append({
                "tier_name": m_name, "price": m_price, "best_for": m_best,
                "benefits": [b.strip() for b in m_benefits.split("\n") if b.strip()]
            })
            st.success(f"'{m_name}' added!")
            st.rerun()

# ──────────────────────────────────────────────
# 8. SMTP CONFIG
# ──────────────────────────────────────────────
with st.expander("📤 SMTP Email Settings"):
    SMTP_PRESETS = {
        "Gmail"            : ("smtp.gmail.com",        "587", "App Password from myaccount.google.com/apppasswords"),
        "Brevo"            : ("smtp-relay.brevo.com",  "587", "SMTP key from Brevo dashboard (NOT your login password)"),
        "Zoho Mail"        : ("smtp.zoho.in",           "587", "Your Zoho account password"),
        "Outlook/Hotmail"  : ("smtp-mail.outlook.com", "587", "Your Outlook password"),
        "Custom / Other"   : ("",                       "587", "Your email provider's password"),
    }
    provider = st.selectbox("Email Provider", list(SMTP_PRESETS.keys()))
    preset_host, preset_port, pwd_hint = SMTP_PRESETS[provider]
    st.caption(f"💡 **{provider} tip:** {pwd_hint}")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        smtp_host = st.text_input("SMTP Host",           value=preset_host)
        smtp_user = st.text_input("Your Email Address",  placeholder="you@gmail.com")
        from_name = st.text_input("Sender Display Name", placeholder="Rahul — TechFest")
    with col_s2:
        smtp_port = st.text_input("SMTP Port",           value=preset_port)
        smtp_pass = st.text_input("Password / App Password", type="password")

# ──────────────────────────────────────────────
# 9. TABS
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 Single Pitch", "🚀 Bulk Processing",
    "📚 Template Library", "🔍 Brand Discovery"
])

# ════════════════════════════════════════════
# TAB 1 — SINGLE PITCH
# ════════════════════════════════════════════
with tab1:
    st.subheader("Target Brand")
    col_a, col_b = st.columns(2)
    with col_a:
        brand_name = st.text_input("Brand Name",    placeholder="e.g. boAt Lifestyle")
        brand_url  = st.text_input("Brand Website", placeholder="https://www.boat-lifestyle.com")
    with col_b:
        pitch_tone = st.selectbox("Pitch Tone", [
            "Corporate/Professional", "Aggressive/Energetic",
            "Playful/Creative", "Culturally Authentic"
        ])
        custom_context = st.text_area("Additional Context",
                                       placeholder="They recently launched a Gen Z campaign...")

    st.markdown("**Sponsorship Activations to Pitch**")
    col_act1, col_act2 = st.columns([3, 1])
    with col_act1:
        activation_input = st.text_input("Add an activation",
                                          placeholder="e.g. Branded Stage, Product Sampling Booth")
    if "activations_list" not in st.session_state:
        st.session_state.activations_list = []
    with col_act2:
        if st.button("➕ Add"):
            if activation_input and activation_input not in st.session_state.activations_list:
                st.session_state.activations_list.append(activation_input)
    if st.session_state.activations_list:
        cols = st.columns(len(st.session_state.activations_list))
        to_remove = None
        for i, act in enumerate(st.session_state.activations_list):
            with cols[i]:
                st.markdown(f"`{act}`")
                if st.button("✕", key=f"rm_{i}"):
                    to_remove = i
        if to_remove is not None:
            st.session_state.activations_list.pop(to_remove)
            st.rerun()

    st.markdown("**📋 Email Template (optional)**")
    all_templates = {"None — Let AI decide structure": ""} | BUILTIN_TEMPLATES | {
        f"⭐ {k}": v for k, v in st.session_state.user_templates.items()
    }
    selected_template_name = st.selectbox(
        "Choose a template", list(all_templates.keys()), key="template_single"
    )
    selected_template = all_templates[selected_template_name]
    if selected_template:
        with st.expander("👁️ Preview template structure"):
            st.text(selected_template)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        research_clicked = st.button("🔍 Research Brand First", use_container_width=True)
    with col_btn2:
        generate_clicked = st.button("⚡ Generate Pitch", use_container_width=True, type="primary")

    if research_clicked:
        if not brand_name:
            st.error("Enter a brand name first.")
        else:
            with st.spinner(f"Researching {brand_name}..."):
                profile = research_brand(brand_name, brand_url)
            st.success("Done!")
            with st.expander("📋 Brand Intelligence Brief", expanded=True):
                st.write(profile)

    if generate_clicked:
        if not event_name or not brand_name:
            st.error("Fill in Event Name and Brand Name first.")
        else:
            with st.spinner(f"Researching {brand_name} and drafting pitch..."):
                profile      = research_brand(brand_name, brand_url)
                tier_suggest = suggest_tier_for_brand(profile, st.session_state.sponsorship_tiers)
                sub, body    = generate_with_retry(
                    brand_name, brand_url, pitch_tone, custom_context,
                    st.session_state.activations_list, profile,
                    selected_template, tier_suggest
                )
                st.session_state.single_email_subject = sub
                st.session_state.single_email_body    = body
            st.success("Pitch generated!")
            if tier_suggest:
                st.info(f"🏆 **Tier Suggested:** {tier_suggest}")
            with st.expander("💾 Save this email structure as a template?"):
                tpl_name = st.text_input("Template name", placeholder="e.g. My winning F&B pitch",
                                          key="save_tpl_name")
                if st.button("Save as Template", key="save_tpl_btn"):
                    if tpl_name:
                        st.session_state.user_templates[tpl_name] = st.session_state.single_email_body
                        st.success(f"Saved as '{tpl_name}'!")

    if st.session_state.single_email_body:
        st.divider()
        st.markdown(f"**✉️ Subject:** `{st.session_state.single_email_subject}`")

        col_edit, col_ai = st.columns(2)
        with col_edit:
            st.markdown("**Manual Editor**")
            edited_body = st.text_area("", value=st.session_state.single_email_body,
                                        height=320, label_visibility="collapsed")
            if st.button("💾 Save Edit"):
                st.session_state.single_email_body = edited_body
                st.success("Saved!")
        with col_ai:
            st.markdown("**AI Refinement**")
            refinement = st.text_input("Command",
                                        placeholder="Make it more concise / add urgency / change CTA...")
            if st.button("🔄 Refine with AI"):
                if refinement:
                    with st.spinner("Rewriting..."):
                        ref_prompt = f"""Rewrite this email based on: "{refinement}"
Output ONLY the new email body. No subject line. No markdown. No asterisks or bold text. Plain text only.

ORIGINAL:
{st.session_state.single_email_body}"""
                        st.session_state.single_email_body = model.generate_content(ref_prompt).text.strip()
                        st.rerun()

        st.divider()
        st.markdown("**📤 Send This Email**")
        col_rec, col_prev = st.columns([3, 1])
        with col_rec:
            to_email_single = st.text_input("Recipient Email",
                                             placeholder="marketing@brandname.com", key="to_single")
        with col_prev:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("👁️ Preview", use_container_width=True, key="preview_single"):
                st.session_state.show_preview_single = True

        if st.session_state.show_preview_single:
            with st.expander("📧 Email Preview — check before sending", expanded=True):
                st.markdown(f"**To:** `{to_email_single or '(no recipient entered)'}`")
                st.markdown(f"**From:** `{from_name} <{smtp_user}>`")
                st.markdown(f"**Subject:** `{st.session_state.single_email_subject}`")
                st.divider()
                st.text(st.session_state.single_email_body)

        attach_files = st.file_uploader(
            "📎 Attach Files (sponsorship deck, brochure, etc.)",
            accept_multiple_files=True, key="attach_single"
        )

        if st.button("🚀 Send Email Now", type="primary", use_container_width=True, key="send_single"):
            if not smtp_user or not smtp_pass:
                st.error("Fill in SMTP settings above first.")
            elif not to_email_single:
                st.error("Enter a recipient email address.")
            else:
                with st.spinner(f"Sending to {to_email_single}..."):
                    ok, msg = send_email_smtp(
                        smtp_host, smtp_port, smtp_user, smtp_pass,
                        from_name, to_email_single,
                        st.session_state.single_email_subject,
                        st.session_state.single_email_body,
                        attachments=list(attach_files) if attach_files else None
                    )
                if ok:
                    st.success(msg)
                    st.session_state.show_preview_single = False
                else:
                    st.error(msg)


# ════════════════════════════════════════════
# TAB 2 — BULK PROCESSING
# ════════════════════════════════════════════
with tab2:
    st.subheader("Bulk Lead Processing")
    uploaded_file = st.file_uploader(
        "Upload CSV (Brand Name, Website URL, Desired Vibe, Recipient Email)", type=["csv"]
    )
    if uploaded_file:
        grid_data = pd.read_csv(uploaded_file)
        grid_data.columns = [c.strip() for c in grid_data.columns]
    else:
        grid_data = pd.DataFrame([{
            "Brand Name": "", "Website URL": "",
            "Desired Vibe": "Corporate/Professional", "Recipient Email": ""
        }])
    if "Recipient Email" not in grid_data.columns:
        grid_data["Recipient Email"] = ""

    edited_df = st.data_editor(grid_data, num_rows="dynamic", use_container_width=True,
        column_config={"Desired Vibe": st.column_config.SelectboxColumn(
            "Desired Vibe",
            options=["Corporate/Professional", "Aggressive/Energetic",
                     "Playful/Creative", "Culturally Authentic"],
            required=True
        )}
    )

    research_first = st.checkbox("🔍 Research each brand before generating", value=True)

    st.markdown("**📋 Email Template (applies to all rows)**")
    all_templates_bulk = {"None — Let AI decide structure": ""} | BUILTIN_TEMPLATES | {
        f"⭐ {k}": v for k, v in st.session_state.user_templates.items()
    }
    selected_bulk_tpl = st.selectbox("Choose a template", list(all_templates_bulk.keys()), key="template_bulk")
    selected_bulk_template = all_templates_bulk[selected_bulk_tpl]
    if selected_bulk_template:
        with st.expander("👁️ Preview template"):
            st.text(selected_bulk_template)

    if st.session_state.sponsorship_tiers:
        st.info(f"🏆 {len(st.session_state.sponsorship_tiers)} tiers loaded — AI will suggest best tier per brand.")

    if st.button("🚀 Run Bulk Engine", type="primary"):
        run_df = edited_df[edited_df["Brand Name"].str.strip() != ""].copy().reset_index(drop=True)
        if run_df.empty:
            st.error("Add at least one brand.")
        else:
            for col in ["Generated_Subject", "Generated_Body", "Brand_Profile", "Tier_Suggestion"]:
                run_df[col] = ""
            progress_bar = st.progress(0)
            status_text  = st.empty()
            total = len(run_df)
            for i, row in run_df.iterrows():
                brand = row["Brand Name"]
                url   = row.get("Website URL", "")
                vibe  = row.get("Desired Vibe", "Corporate/Professional")
                status_text.text(f"[{i+1}/{total}] {'Researching' if research_first else 'Generating'}: {brand}...")
                profile = tier_suggest = ""
                if research_first:
                    profile = research_brand(brand, url)
                    run_df.at[i, "Brand_Profile"] = profile
                    tier_suggest = suggest_tier_for_brand(profile, st.session_state.sponsorship_tiers)
                    run_df.at[i, "Tier_Suggestion"] = tier_suggest
                    time.sleep(0.5)
                status_text.text(f"[{i+1}/{total}] Generating pitch: {brand}...")
                sub, body = generate_with_retry(
                    brand, url, vibe, brand_profile=profile,
                    template=selected_bulk_template, tier_suggestion=tier_suggest
                )
                run_df.at[i, "Generated_Subject"] = sub
                run_df.at[i, "Generated_Body"]    = body
                progress_bar.progress((i + 1) / total)
                time.sleep(1)
            status_text.text(f"✅ Done! {total} pitches generated.")
            st.session_state.bulk_data = run_df
            st.rerun()

    if st.session_state.bulk_data is not None:
        st.divider()
        st.subheader("Review & Refine Results")
        df_results     = st.session_state.bulk_data
        selected_brand = st.selectbox("Select brand to review:", df_results["Brand Name"].tolist())
        row            = df_results[df_results["Brand Name"] == selected_brand].iloc[0]
        current_sub    = row["Generated_Subject"]
        current_body   = row["Generated_Body"]

        if row.get("Brand_Profile", ""):
            with st.expander(f"📋 Brand Intelligence: {selected_brand}"):
                st.write(row["Brand_Profile"])
        if row.get("Tier_Suggestion", ""):
            st.info(f"🏆 **Tier Suggestion:** {row['Tier_Suggestion']}")

        st.markdown(f"**✉️ Subject:** `{current_sub}`")

        if st.button("👁️ Preview This Email", key="preview_bulk"):
            with st.expander(f"📧 Preview — {selected_brand}", expanded=True):
                st.markdown(f"**To:** `{row.get('Recipient Email', '(no email in grid)')}`")
                st.markdown(f"**From:** `{from_name} <{smtp_user}>`")
                st.markdown(f"**Subject:** `{current_sub}`")
                st.divider()
                st.text(current_body)

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            st.markdown("**Manual Editor**")
            edited_bulk = st.text_area("", value=current_body, height=320, label_visibility="collapsed")
            if st.button("💾 Save to Grid"):
                st.session_state.bulk_data.loc[
                    st.session_state.bulk_data["Brand Name"] == selected_brand, "Generated_Body"
                ] = edited_bulk
                st.success("Saved!")
        with col_b2:
            st.markdown("**AI Refinement**")
            refine_bulk = st.text_input("Command", placeholder="Shorten it / add a case study angle...")
            if st.button("🔄 Refine with AI (Bulk)"):
                if refine_bulk:
                    with st.spinner("Rewriting..."):
                        ref_prompt = f"""Rewrite based on: "{refine_bulk}"\nOutput ONLY the new email body. No markdown. No asterisks. Plain text only.\n\nORIGINAL:\n{current_body}"""
                        new_body = model.generate_content(ref_prompt).text.strip()
                        st.session_state.bulk_data.loc[
                            st.session_state.bulk_data["Brand Name"] == selected_brand, "Generated_Body"
                        ] = new_body
                        st.rerun()

        st.divider()
        col_ex1, col_ex2 = st.columns(2)
        with col_ex1:
            st.download_button("📥 Download All (CSV)",
                                data=st.session_state.bulk_data.to_csv(index=False).encode("utf-8"),
                                file_name="vibepitch_campaigns.csv", mime="text/csv",
                                use_container_width=True)
        with col_ex2:
            clean_df = st.session_state.bulk_data[
                ~st.session_state.bulk_data["Generated_Body"].str.startswith("ERROR", na=False)
            ]
            st.download_button("✅ Download Clean Only",
                                data=clean_df.to_csv(index=False).encode("utf-8"),
                                file_name="vibepitch_clean.csv", mime="text/csv",
                                use_container_width=True)

        st.divider()
        st.markdown("**📤 Send All Emails**")
        st.caption("Reads Recipient Email column. Skips rows with no email or errors.")
        bulk_attach = st.file_uploader("📎 Attach to ALL emails (optional)",
                                        accept_multiple_files=True, key="attach_bulk")
        if st.button("🚀 Send All Generated Emails", type="primary", use_container_width=True):
            if not smtp_user or not smtp_pass:
                st.error("Fill in SMTP settings above first.")
            else:
                if "Recipient Email" not in st.session_state.bulk_data.columns:
                    st.error("No Recipient Email column found.")
                else:
                    sendable = st.session_state.bulk_data[
                        st.session_state.bulk_data["Recipient Email"].str.strip().ne("") &
                        ~st.session_state.bulk_data["Generated_Body"].str.startswith("ERROR", na=False)
                    ]
                    if sendable.empty:
                        st.error("No rows with Recipient Email found.")
                    else:
                        send_progress = st.progress(0)
                        send_log      = st.empty()
                        results       = []
                        total_send    = len(sendable)
                        for i, (_, srow) in enumerate(sendable.iterrows()):
                            send_log.text(f"Sending to {srow['Recipient Email']}...")
                            ok, msg = send_email_smtp(
                                smtp_host, smtp_port, smtp_user, smtp_pass,
                                from_name, srow["Recipient Email"],
                                srow["Generated_Subject"], srow["Generated_Body"],
                                attachments=list(bulk_attach) if bulk_attach else None
                            )
                            results.append({"Brand": srow["Brand Name"],
                                            "Email": srow["Recipient Email"], "Status": msg})
                            send_progress.progress((i + 1) / total_send)
                            time.sleep(1.5)
                        send_log.text("Done!")
                        st.dataframe(pd.DataFrame(results), use_container_width=True)


# ════════════════════════════════════════════
# TAB 3 — TEMPLATE LIBRARY
# ════════════════════════════════════════════
with tab3:
    st.subheader("📚 Template Library")
    st.caption("Templates guide the AI's structure. All content is rewritten with live brand research.")

    st.markdown("### 🏭 Built-in Industry Templates")
    for tname, tbody in BUILTIN_TEMPLATES.items():
        with st.expander(tname):
            st.text(tbody.strip())

    st.divider()
    st.markdown("### ⭐ Your Saved Templates")
    if not st.session_state.user_templates:
        st.info("No saved templates yet. Generate an email in Single Pitch and save it as a template.")
    else:
        for tname, tbody in list(st.session_state.user_templates.items()):
            with st.expander(f"⭐ {tname}"):
                edited_tpl = st.text_area("", value=tbody, height=200,
                                           key=f"edit_tpl_{tname}", label_visibility="collapsed")
                col_tl1, col_tl2 = st.columns(2)
                with col_tl1:
                    if st.button("💾 Save Changes", key=f"save_tpl_{tname}"):
                        st.session_state.user_templates[tname] = edited_tpl
                        st.success("Updated!")
                with col_tl2:
                    if st.button("🗑️ Delete", key=f"del_tpl_{tname}"):
                        del st.session_state.user_templates[tname]
                        st.rerun()

    st.divider()
    st.markdown("### ✏️ Create New Template")
    new_tpl_name = st.text_input("Template Name", placeholder="e.g. Aggressive Tech Pitch")
    new_tpl_body = st.text_area("Template Structure", height=200,
                                 placeholder="STRUCTURE:\n- Hook: ...\n- Problem: ...\n- Solution: ...\n- CTA: ...")
    if st.button("➕ Add to Library", type="primary"):
        if new_tpl_name and new_tpl_body:
            st.session_state.user_templates[new_tpl_name] = new_tpl_body
            st.success(f"'{new_tpl_name}' added!")
            st.rerun()
        else:
            st.error("Fill in both name and structure.")


# ════════════════════════════════════════════
# TAB 4 — BRAND DISCOVERY
# ════════════════════════════════════════════
with tab4:
    st.subheader("🔍 Brand Discovery Engine")
    st.caption("Type the domains you want to target — get real brand suggestions with full intelligence briefs.")

    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        domain_input = st.text_input(
            "Domains (comma separated)",
            placeholder="e.g. beverages, fintech, fashion, edtech, gaming"
        )
    with col_d2:
        brands_per_domain = st.number_input("Per domain", min_value=1, max_value=5, value=3)

    event_ctx = st.text_input(
        "Describe your event (for better matching)",
        placeholder="e.g. 3-day tech fest, 10,000 students, IIT Delhi, engineering & startups"
    )

    if st.button("🔍 Discover Brands", type="primary", use_container_width=True):
        if not domain_input:
            st.error("Enter at least one domain.")
        else:
            domains = [d.strip() for d in domain_input.split(",") if d.strip()]
            with st.spinner(f"Finding brands across {len(domains)} domains..."):
                results = discover_brands(
                    domains,
                    event_ctx or event_name or "a college tech fest",
                    brands_per_domain
                )
                st.session_state.discovered_brands = results

    if st.session_state.discovered_brands:
        st.divider()
        st.markdown(f"### 🎯 {len(st.session_state.discovered_brands)} Brands Found")

        # Group by domain
        by_domain = {}
        for b in st.session_state.discovered_brands:
            d = b.get("domain", "Other")
            by_domain.setdefault(d, []).append(b)

        for domain, brands in by_domain.items():
            st.markdown(f"#### {domain}")
            for brand in brands:
                with st.expander(f"**{brand.get('brand_name', 'Unknown')}** — {brand.get('website', '')}"):
                    col_i1, col_i2 = st.columns(2)
                    with col_i1:
                        st.markdown(f"**Core Business:** {brand.get('core_business', 'N/A')}")
                        st.markdown(f"**Target Audience:** {brand.get('target_audience', 'N/A')}")
                        st.markdown(f"**Brand Personality:** {brand.get('brand_personality', 'N/A')}")
                    with col_i2:
                        st.markdown(f"**Marketing Goals:** {brand.get('marketing_goals', 'N/A')}")
                        st.markdown(f"**Sponsorship Fit:** {brand.get('sponsorship_fit', 'N/A')}")
                        st.markdown(f"**Est. Budget:** {brand.get('estimated_budget', 'N/A')}")

                    if st.button(f"➕ Add to Bulk Grid", key=f"add_bulk_{brand.get('brand_name')}"):
                        st.success(f"Copy '{brand.get('brand_name')}' and '{brand.get('website')}' into the Bulk Processing tab grid manually.")

        st.divider()
        disc_df = pd.DataFrame(st.session_state.discovered_brands)
        st.download_button(
            "📥 Export Discovered Brands (CSV)",
            data=disc_df.to_csv(index=False).encode("utf-8"),
            file_name="vibepitch_discovered_brands.csv",
            mime="text/csv", use_container_width=True
        )
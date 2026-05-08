import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import base64
import requests

# ---------- CONFIG ----------
st.set_page_config(page_title="🧙‍♂️ CoachGnome – AI Call Coach", layout="wide")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1pKtkFr5x4_RRj-ruXnLZl3D4_IBzkyOnynWjjPac0jo/export?format=csv"

# ---------- AUDIO ----------
@st.cache_data(ttl=3600)
def download_audio_from_gdrive(drive_url, filename):
    file_id = None
    if "id=" in drive_url:
        file_id = drive_url.split("id=")[1].split("&")[0]
    elif "/d/" in drive_url:
        file_id = drive_url.split("/d/")[1].split("/")[0]
    if not file_id:
        return None
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    for attempt, timeout in enumerate([60, 90, 120]):
        try:
            session = requests.Session()
            response = session.get(download_url, stream=True, timeout=timeout)
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    response = session.get(download_url, params={'confirm': value, 'id': file_id}, stream=True, timeout=timeout)
                    break
            audio_bytes = b''.join(chunk for chunk in response.iter_content(8192) if chunk)
            return base64.b64encode(audio_bytes).decode()
        except requests.exceptions.Timeout:
            if attempt < 2:
                st.warning(f"Download timed out, retrying... ({attempt + 2}/3)")
            else:
                st.error("Failed to download audio after 3 attempts.")
                return None
        except Exception as e:
            st.error(f"Error downloading audio: {e}")
            return None

# ---------- LOAD DATA ----------
@st.cache_data(ttl=60)
def load_data():
    try:
        df = pd.read_csv(SHEET_URL)
        df['feedback_parsed'] = df['feedback_json'].apply(parse_feedback)
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

def parse_feedback(feedback_str):
    if pd.isna(feedback_str) or not feedback_str:
        return {}
    try:
        clean_str = feedback_str.strip()
        if clean_str.startswith('```'):
            clean_str = clean_str.split('```')[1]
            if clean_str.startswith('json'):
                clean_str = clean_str[4:]
        return json.loads(clean_str.strip())
    except:
        return {}

def filter_by_time_period(df, time_filter):
    if df.empty or 'date' not in df.columns:
        return df
    try:
        df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    except:
        return df
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if time_filter == "Today":
        return df[df['date_parsed'] >= today_start]
    elif time_filter == "This Week":
        return df[df['date_parsed'] >= today_start - timedelta(days=today_start.weekday())]
    elif time_filter == "This Month":
        return df[df['date_parsed'] >= today_start.replace(day=1)]
    return df

def aggregate_rep_performance(df, agent_name):
    agent_calls = df[df['agent_name'] == agent_name].copy()
    if 'date_parsed' in agent_calls.columns:
        agent_calls = agent_calls.sort_values('date_parsed')

    agg = {
        'total_calls': len(agent_calls),
        'outcomes': {'closed': 0, 'lost': 0, 'follow_up': 0},
        'scores': {k: [] for k in ['overall', 'active_listening', 'probing_depth', 'emotional_intelligence',
                                    'value_based_selling', 'spin_effectiveness', 'sandler_effectiveness', 'objection_handling']},
        'common_strengths': [],
        'common_weaknesses': [],
        'active_listening_patterns': [],
        'probing_patterns': [],
        'emotional_cue_patterns': [],
        'objection_patterns': [],
        'spin_gaps': {'situation': 0, 'problem': 0, 'implication': 0, 'need_payoff': 0},
        'sandler_gaps': {'upfront_contract': 0, 'pain_depth_surface': 0, 'budget_qualified': 0, 'decision_process': 0},
        'behavior_timeline': []
    }

    for _, row in agent_calls.iterrows():
        feedback = row['feedback_parsed']
        if not feedback:
            continue

        outcome = feedback.get('call_outcome', '')
        if outcome == 'closed':
            agg['outcomes']['closed'] += 1
        elif outcome == 'lost':
            agg['outcomes']['lost'] += 1
        elif outcome in ['follow-up-scheduled', 'needs-callback']:
            agg['outcomes']['follow_up'] += 1

        for k in agg['scores']:
            v = feedback.get('call_score', {}).get(k, 0)
            if v > 0:
                agg['scores'][k].append(v)

        agg['common_strengths'].extend(feedback.get('what_went_well', []))
        agg['common_weaknesses'].extend(feedback.get('opportunities_to_improve', []))

        for fail in feedback.get('active_listening_failures', []):
            agg['active_listening_patterns'].append({'what_was_missed': fail.get('what_was_missed', ''), 'date': row['date'], 'filename': row['filename']})
        for _ in feedback.get('missed_probing_opportunities', []):
            agg['probing_patterns'].append({'date': row['date'], 'filename': row['filename']})
        for miss in feedback.get('emotional_cues_missed', []):
            agg['emotional_cue_patterns'].append({'emotion': miss.get('customer_emotion', ''), 'date': row['date'], 'filename': row['filename']})
        for obj in feedback.get('objection_handling_analysis', []):
            agg['objection_patterns'].append({'objection': obj.get('objection', ''), 'effectiveness': obj.get('effectiveness_rating', 0), 'went_to_discount': obj.get('went_straight_to_discount', False), 'date': row['date'], 'filename': row['filename']})

        spin = feedback.get('spin_analysis', {})
        for k in ['situation', 'problem', 'implication', 'need_payoff']:
            if not spin.get(f'{k}_questions_used'):
                agg['spin_gaps'][k] += 1

        sandler = feedback.get('sandler_analysis', {})
        if not sandler.get('upfront_contract_established'):
            agg['sandler_gaps']['upfront_contract'] += 1
        if sandler.get('pain_depth') == 'surface':
            agg['sandler_gaps']['pain_depth_surface'] += 1
        if not sandler.get('budget_qualified'):
            agg['sandler_gaps']['budget_qualified'] += 1
        if not sandler.get('decision_process_identified'):
            agg['sandler_gaps']['decision_process'] += 1

        # Behavior timeline entry
        discount_count = sum(1 for o in feedback.get('objection_handling_analysis', []) if o.get('went_straight_to_discount'))
        agg['behavior_timeline'].append({
            'date': row.get('date', ''),
            'filename': row['filename'],
            'active_listening': len(feedback.get('active_listening_failures', [])),
            'probing': len(feedback.get('missed_probing_opportunities', [])),
            'emotional_cues': len(feedback.get('emotional_cues_missed', [])),
            'discounting': discount_count,
            'score': feedback.get('call_score', {}).get('overall_score', 0)
        })

    return agg

# ---------- HELPERS ----------
def make_jump_button(player_id, ts, audio_available):
    if not audio_available or not player_id:
        return
    start_seconds = 0
    try:
        if ':' in str(ts):
            parts = str(ts).split(':')
            start_seconds = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            start_seconds = int(float(ts))
    except:
        pass
    components.html(f"""
    <div style="margin-bottom:10px;">
        <button onclick="var p=window.parent.document.getElementById('{player_id}');if(p){{p.currentTime={start_seconds};p.play();window.parent.scrollTo({{top:0,behavior:'smooth'}})}}"
        style="padding:8px 16px;background:#4CAF50;color:white;border:none;border-radius:5px;cursor:pointer;font-weight:bold;font-size:13px;">
            ▶ Jump to {ts}
        </button>
    </div>""", height=55)

def render_what_went_well_item(item):
    """Render a what_went_well item whether it's a dict or string."""
    if isinstance(item, dict):
        ts = item.get('timestamp', '')
        category = item.get('category', '').replace('_', ' ').title()
        what_happened = item.get('what_happened', '')
        exact_quote = item.get('exact_quote', '')
        why_worked = item.get('why_this_worked', '')
        customer_response = item.get('customer_response', '')
        framework = item.get('framework_connection', '')
        coaching_insight = item.get('coaching_insight', '')

        header = f"✓ **[{ts}]** {category}" if ts else f"✓ **{category}**"
        st.success(header)
        if exact_quote:
            st.info(f'💬 *"{exact_quote}"*')
        if what_happened:
            st.write(f"**What happened:** {what_happened}")
        if why_worked:
            st.write(f"**Why it worked:** {why_worked}")
        if customer_response:
            st.caption(f"📊 Customer response: {customer_response}")
        if framework:
            st.caption(f"🎓 {framework}")
        if coaching_insight:
            st.caption(f"💡 {coaching_insight}")
        st.markdown("")
    else:
        st.success(f"✓ {item}")

def render_behavior_tracking(behavior_timeline):
    """Show coaching timeline — is behavior improving?"""
    if not behavior_timeline:
        return

    st.markdown("### 📈 Coaching Behavior Tracker")
    st.caption("Track whether coached behaviors are actually improving across calls")

    behaviors = {
        'active_listening': '🎧 Active Listening Failures',
        'probing': '🔍 Missed Probing Opportunities',
        'emotional_cues': '💭 Emotional Cues Missed',
        'discounting': '💰 Went Straight to Discount'
    }

    for key, label in behaviors.items():
        counts = [e[key] for e in behavior_timeline]
        if not any(c > 0 for c in counts):
            continue

        n = len(counts)
        half = max(1, n // 2)
        first_avg = sum(counts[:half]) / half
        second_avg = sum(counts[half:]) / max(1, n - half)

        if second_avg < first_avg - 0.3:
            trend = "✅ IMPROVING"
            color = "success"
        elif second_avg > first_avg + 0.3:
            trend = "🚨 GETTING WORSE"
            color = "error"
        else:
            trend = "⚠️ PERSISTING"
            color = "warning"

        with st.expander(f"{trend} — {label} ({sum(1 for c in counts if c > 0)} of {n} calls flagged)"):
            for entry in behavior_timeline:
                count = entry[key]
                date = entry['date']
                call_id = entry['filename']
                if count > 0:
                    st.error(f"**{date}** — {count} instance(s) flagged  |  Call: `{call_id}`")
                else:
                    st.success(f"✅ **{date}** — Clean! No {label.lower()} issues  |  Call: `{call_id}`")

# ---------- PAGE ----------
st.title("🧙‍♂️ CoachGnome – AI Call Coach Dashboard")
st.caption("Powered by SPIN Selling + Sandler Methodology ✨")

with st.sidebar:
    st.header("📊 Dashboard Controls")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
    date_filter = st.selectbox("Time Period", ["Today", "This Week", "This Month", "All Time"], key="time_filter")
    st.markdown("---")
    st.caption("💾 Data synced from Google Sheets")
    st.caption("🎓 Coaching analysis by GPT-4o-mini")

raw_df = load_data()

if raw_df.empty:
    st.warning("No data available yet. Upload call recordings to start!")
    st.stop()

df = filter_by_time_period(raw_df, date_filter)

with st.sidebar:
    st.caption(f"📞 Showing {len(df)} of {len(raw_df)} calls")

if df.empty and date_filter != "All Time":
    st.info(f"No calls found for '{date_filter}'. Try a different time period!")
    st.stop()

# ---------- TABS ----------
tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Executive Summary", "🏆 Rep Deep Dive",
    "🌟 Exceptional Moments", "📊 Team Analytics", "🔍 Call Search"
])

# ===== TAB 0: EXECUTIVE SUMMARY =====
with tab0:
    st.header("📋 Executive Summary – Quick Coaching Priorities")
    st.caption("What needs immediate attention across the team")

    all_agents = df['agent_name'].dropna().unique()
    agent_performance = {}

    for agent in all_agents:
        agent_calls = df[df['agent_name'] == agent]
        perf = {'total_calls': len(agent_calls), 'listening_fails': 0, 'probing_fails': 0,
                'emotional_fails': 0, 'objection_fails': 0, 'discount_count': 0,
                'exceptional_count': 0, 'avg_score': 0, 'scores': []}

        for _, row in agent_calls.iterrows():
            feedback = row['feedback_parsed']
            if not feedback:
                continue
            perf['listening_fails'] += len(feedback.get('active_listening_failures', []))
            perf['probing_fails'] += len(feedback.get('missed_probing_opportunities', []))
            perf['emotional_fails'] += len(feedback.get('emotional_cues_missed', []))
            objections = feedback.get('objection_handling_analysis', [])
            perf['objection_fails'] += len(objections)
            perf['discount_count'] += sum(1 for o in objections if o.get('went_straight_to_discount'))
            perf['exceptional_count'] += len([m for m in feedback.get('exceptional_moments', []) if m.get('shareworthy')])
            overall = feedback.get('call_score', {}).get('overall_score', 0)
            if overall > 0:
                perf['scores'].append(overall)

        if perf['scores']:
            perf['avg_score'] = sum(perf['scores']) / len(perf['scores'])
        agent_performance[agent] = perf

    st.subheader("🚨 Top Priority Issues")
    col1, col2, col3 = st.columns(3)

    struggling_listening = sorted([(a, p['listening_fails']) for a, p in agent_performance.items()], key=lambda x: x[1], reverse=True)[:3]
    struggling_probing = sorted([(a, p['probing_fails']) for a, p in agent_performance.items()], key=lambda x: x[1], reverse=True)[:3]
    struggling_discount = sorted([(a, p['discount_count']) for a, p in agent_performance.items()], key=lambda x: x[1], reverse=True)[:3]

    with col1:
        st.markdown("### 🎧 Active Listening")
        if struggling_listening and struggling_listening[0][1] > 0:
            st.error("**Needs Immediate Attention:**")
            for agent, count in struggling_listening:
                if count > 0:
                    st.write(f"- **{agent}**: {count} failures")
            st.info("**Quick Tip:** Mirror & Build — repeat what they said, then ask a follow-up.")
        else:
            st.success("✓ Team performing well!")

    with col2:
        st.markdown("### 🔍 Probing Depth")
        if struggling_probing and struggling_probing[0][1] > 0:
            st.warning("**Needs Focus:**")
            for agent, count in struggling_probing:
                if count > 0:
                    st.write(f"- **{agent}**: {count} missed")
            st.info("**Quick Tip:** Never accept the first answer. Dig at least 2 levels deeper.")
        else:
            st.success("✓ Team digging deep!")

    with col3:
        st.markdown("### 💰 Discount Jumping")
        if struggling_discount and struggling_discount[0][1] > 0:
            st.error("**Critical Issue:**")
            for agent, count in struggling_discount:
                if count > 0:
                    st.write(f"- **{agent}**: {count} times")
            st.info("**Quick Tip:** Before ANY discount — 'What happens if your pool stays green?' Establish cost of inaction first.")
        else:
            st.success("✓ Value-selling strong!")

    st.markdown("---")
    st.subheader("🏆 Performance Tiers")

    top_performers = [(a, p) for a, p in agent_performance.items() if p['avg_score'] >= 7]
    developing = [(a, p) for a, p in agent_performance.items() if 5 <= p['avg_score'] < 7]
    needs_support = [(a, p) for a, p in agent_performance.items() if 0 < p['avg_score'] < 5]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 🥇 Top Performers (7+)")
        for agent, perf in sorted(top_performers, key=lambda x: x[1]['avg_score'], reverse=True):
            st.success(f"**{agent}**: {perf['avg_score']:.1f}/10")
            if perf['exceptional_count'] > 0:
                st.caption(f"✨ {perf['exceptional_count']} exceptional moments")
        if not top_performers:
            st.info("Building data...")

    with col2:
        st.markdown("### 📈 Developing (5-6.9)")
        for agent, perf in sorted(developing, key=lambda x: x[1]['avg_score'], reverse=True):
            st.warning(f"**{agent}**: {perf['avg_score']:.1f}/10")
        if not developing:
            st.info("No agents in this tier")

    with col3:
        st.markdown("### 🆘 Needs Support (<5)")
        for agent, perf in sorted(needs_support, key=lambda x: x[1]['avg_score'], reverse=True):
            st.error(f"**{agent}**: {perf['avg_score']:.1f}/10")
            issues = []
            if perf['listening_fails'] > 3:
                issues.append("Active Listening")
            if perf['probing_fails'] > 3:
                issues.append("Probing")
            if perf['discount_count'] > 2:
                issues.append("Discounting")
            if issues:
                st.caption(f"⚠️ Focus: {', '.join(issues)}")
        if not needs_support:
            st.success("No agents need urgent support")

    st.markdown("---")
    st.subheader("✨ Skill Spotlight – Learn from the Best")

    exceptional_by_category = {k: {} for k in ['objection_handling', 'empathy', 'active_listening', 'probing']}
    for _, row in df.iterrows():
        feedback = row['feedback_parsed']
        if not feedback:
            continue
        agent = row['agent_name']
        for moment in feedback.get('exceptional_moments', []):
            if moment.get('shareworthy'):
                cat = moment.get('category', 'general')
                if cat in exceptional_by_category:
                    exceptional_by_category[cat][agent] = exceptional_by_category[cat].get(agent, 0) + 1

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🛡️ Objection Handling Champions")
        if exceptional_by_category['objection_handling']:
            for agent, count in sorted(exceptional_by_category['objection_handling'].items(), key=lambda x: x[1], reverse=True)[:3]:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")

        st.markdown("### 🔍 Probing Masters")
        if exceptional_by_category['probing']:
            for agent, count in sorted(exceptional_by_category['probing'].items(), key=lambda x: x[1], reverse=True)[:3]:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")

    with col2:
        st.markdown("### ❤️ Empathy Experts")
        if exceptional_by_category['empathy']:
            for agent, count in sorted(exceptional_by_category['empathy'].items(), key=lambda x: x[1], reverse=True)[:3]:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")

        st.markdown("### 🎧 Active Listening Leaders")
        if exceptional_by_category['active_listening']:
            for agent, count in sorted(exceptional_by_category['active_listening'].items(), key=lambda x: x[1], reverse=True)[:3]:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")

    st.markdown("---")
    st.subheader("⚡ Recommended Actions")
    total_listening = sum(p['listening_fails'] for p in agent_performance.values())
    total_probing = sum(p['probing_fails'] for p in agent_performance.values())
    total_discount = sum(p['discount_count'] for p in agent_performance.values())
    actions = []
    if total_listening > len(df) * 0.3:
        actions.append("🚨 **Team Training Needed:** Active Listening — over 30% of calls show failures")
    if total_probing > len(df) * 0.4:
        actions.append("⚠️ **Team Training Needed:** SPIN Selling — agents stopping at surface answers")
    if total_discount > len(df) * 0.2:
        actions.append("🔴 **Urgent:** Value-based selling training — too many reps jumping to discounts")
    for agent, perf in needs_support:
        actions.append(f"👤 **1-on-1 Coaching:** {agent} needs immediate support (score: {perf['avg_score']:.1f})")
    for action in actions:
        st.warning(action)
    if not actions:
        st.success("✅ Team is performing well! Continue monitoring and celebrating wins.")

# ===== TAB 1: REP DEEP DIVE =====
with tab1:
    st.header("🏆 Rep Performance Deep Dive")
    agents = df['agent_name'].dropna().unique()

    if len(agents) == 0:
        st.info("No agent data available yet")
    else:
        selected_agent = st.selectbox("Select Agent:", sorted(agents))
        agg_data = aggregate_rep_performance(df, selected_agent)

        st.subheader(f"📈 {selected_agent} – Overall Performance")
        col1, col2, col3, col4 = st.columns(4)
        total_outcomes = agg_data['outcomes']['closed'] + agg_data['outcomes']['lost']
        close_rate = (agg_data['outcomes']['closed'] / total_outcomes * 100) if total_outcomes > 0 else 0
        avg_overall = sum(agg_data['scores']['overall']) / len(agg_data['scores']['overall']) if agg_data['scores']['overall'] else 0

        with col1:
            st.metric("Total Calls", agg_data['total_calls'])
        with col2:
            st.metric("Close Rate", f"{close_rate:.1f}%")
        with col3:
            st.metric("Avg Score", f"{avg_overall:.1f}/10")
        with col4:
            st.metric("W/L Record", f"{agg_data['outcomes']['closed']}/{agg_data['outcomes']['lost']}")

        st.markdown("---")

        # Behavior tracker
        render_behavior_tracking(agg_data['behavior_timeline'])

        st.markdown("---")
        st.subheader("🎯 Skill Scores Breakdown")
        score_cols = st.columns(4)
        skill_names = [
            ('active_listening', '🎧 Active Listening'),
            ('probing_depth', '🔍 Probing Depth'),
            ('emotional_intelligence', '💭 Emotional IQ'),
            ('value_based_selling', '💰 Value Selling'),
            ('spin_effectiveness', '🎯 SPIN'),
            ('sandler_effectiveness', '💼 Sandler'),
            ('objection_handling', '🛡️ Objections')
        ]
        for idx, (key, label) in enumerate(skill_names):
            with score_cols[idx % 4]:
                scores = agg_data['scores'].get(key, [])
                avg = sum(scores) / len(scores) if scores else 0
                st.metric(label, f"{avg:.1f}/10")

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🚨 Critical Patterns")
            if agg_data['active_listening_patterns']:
                with st.expander(f"🎧 Active Listening Issues ({len(agg_data['active_listening_patterns'])} instances)", expanded=True):
                    patterns = {}
                    for p in agg_data['active_listening_patterns']:
                        issue = p['what_was_missed']
                        patterns[issue] = patterns.get(issue, 0) + 1
                    for issue, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]:
                        st.error(f"**{count}x**: {issue}")

            if agg_data['probing_patterns']:
                with st.expander(f"🔍 Probing Issues ({len(agg_data['probing_patterns'])} instances)"):
                    st.warning(f"Stopped at surface level **{len(agg_data['probing_patterns'])} times** across calls")

            if agg_data['emotional_cue_patterns']:
                with st.expander(f"💭 Emotional Cues Missed ({len(agg_data['emotional_cue_patterns'])} instances)"):
                    emotions = {}
                    for p in agg_data['emotional_cue_patterns']:
                        emotions[p['emotion']] = emotions.get(p['emotion'], 0) + 1
                    for emotion, count in sorted(emotions.items(), key=lambda x: x[1], reverse=True):
                        st.warning(f"**{emotion.title()}**: {count}x")

        with col2:
            st.subheader("🎓 Framework Gaps")
            spin_total = agg_data['total_calls']
            with st.expander("🎯 SPIN Selling Gaps", expanded=True):
                st.write(f"**Situation Questions**: Missing in {agg_data['spin_gaps']['situation']}/{spin_total} calls")
                st.write(f"**Problem Questions**: Missing in {agg_data['spin_gaps']['problem']}/{spin_total} calls")
                st.write(f"**⚠️ Implication Questions**: Missing in {agg_data['spin_gaps']['implication']}/{spin_total} calls")
                st.write(f"**Need-Payoff Questions**: Missing in {agg_data['spin_gaps']['need_payoff']}/{spin_total} calls")
                if agg_data['spin_gaps']['implication'] > spin_total * 0.5:
                    st.error("🚨 **CRITICAL**: Not building value with Implication questions!")

            with st.expander("💼 Sandler Methodology Gaps"):
                st.write(f"**Up-Front Contract**: Missing in {agg_data['sandler_gaps']['upfront_contract']}/{spin_total} calls")
                st.write(f"**Surface Pain Only**: {agg_data['sandler_gaps']['pain_depth_surface']}/{spin_total} calls")
                st.write(f"**Budget Not Qualified**: {agg_data['sandler_gaps']['budget_qualified']}/{spin_total} calls")
                st.write(f"**Decision Process Unknown**: {agg_data['sandler_gaps']['decision_process']}/{spin_total} calls")

            if agg_data['objection_patterns']:
                with st.expander(f"🛡️ Objection Handling ({len(agg_data['objection_patterns'])} objections)"):
                    went_to_discount = sum(1 for o in agg_data['objection_patterns'] if o['went_to_discount'])
                    avg_eff = sum(o['effectiveness'] for o in agg_data['objection_patterns']) / len(agg_data['objection_patterns'])
                    if went_to_discount > 0:
                        st.error(f"⚠️ Went straight to discount **{went_to_discount} times**")
                    st.write(f"**Avg Effectiveness**: {avg_eff:.1f}/10")

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("💪 Common Strengths")
            if agg_data['common_strengths']:
                strength_counts = {}
                for s in agg_data['common_strengths']:
                    text = s.get('what_happened', str(s)) if isinstance(s, dict) else str(s)
                    strength_counts[text] = strength_counts.get(text, 0) + 1
                for strength, count in sorted(strength_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                    st.success(f"✓ {strength[:100]} ({count} calls)")
            else:
                st.info("Building performance history...")

        with col2:
            st.subheader("📈 Top Growth Areas")
            if agg_data['common_weaknesses']:
                weakness_counts = {}
                for w in agg_data['common_weaknesses']:
                    text = w if isinstance(w, str) else str(w)
                    weakness_counts[text] = weakness_counts.get(text, 0) + 1
                for weakness, count in sorted(weakness_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                    st.warning(f"⚠️ {weakness[:100]} ({count} calls)")
            else:
                st.info("Building performance history...")

        st.markdown("---")
        st.subheader(f"📞 All Calls ({agg_data['total_calls']})")

        agent_calls = df[df['agent_name'] == selected_agent]

        for idx, row in agent_calls.iterrows():
            feedback = row['feedback_parsed']
            outcome = feedback.get('call_outcome', 'unknown') if feedback else 'unknown'
            outcome_icons = {"closed": "🟢", "lost": "🔴", "follow-up-scheduled": "🟡", "needs-callback": "🟠"}
            icon = outcome_icons.get(outcome, "⚪")
            score = feedback.get('call_score', {}).get('overall_score', 0) if feedback else 0

            with st.expander(f"{icon} {row['filename']} — {outcome.upper()} | Score: {score}/10 ({row['date']})"):
                if feedback:
                    # Call summary header
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**Summary:** {feedback.get('summary', '')}")
                        st.write(f"**Customer Intent:** {feedback.get('customer_intent', '')}")
                    with col2:
                        st.write(f"**Overall Score:** {score}/10")
                        st.write(f"**Close Reason:** {feedback.get('close_reason', '')}")
                    with col3:
                        disposition = row.get('disposition', '')
                        if pd.notna(disposition) and disposition:
                            st.write(f"**Five9 Disposition:** {disposition}")
                        st.write(f"**Duration:** {row.get('call_duration', 'N/A')}s")

                    st.markdown("---")

                    # ============================================================
                    # COACH'S NOTE — Heather-style personality message to the rep
                    # ============================================================
                    rep_message = feedback.get('rep_feedback_message', '')
                    if rep_message:
                        st.markdown("### 📣 Coach's Note")
                        st.markdown(
                            f"""<div style="background:#1a472a;border-left:4px solid #4CAF50;padding:16px;border-radius:8px;margin-bottom:16px;">
                            <p style="color:#ffffff;font-size:15px;margin:0;">🧙‍♂️ <strong>CoachGnome says:</strong> {rep_message}</p>
                            </div>""",
                            unsafe_allow_html=True
                        )
                        st.markdown("---")

                    # ============================================================
                    # AUDIO PLAYER
                    # ============================================================
                    audio_available = False
                    player_id = None

                    audio_url = row.get('audio_url', '')
                    if pd.notna(audio_url) and audio_url and 'drive.google.com' in str(audio_url):
                        with st.spinner("🎧 Loading audio player..."):
                            audio_base64 = download_audio_from_gdrive(audio_url, row['filename'])
                        if audio_base64:
                            audio_available = True
                            player_id = f"player_{row['filename'].replace(' ', '_').replace('.', '_')}"
                            st.markdown(f"""
                            <div style="position:sticky;top:0;z-index:1000;background:white;padding:12px;border:2px solid #4CAF50;border-radius:8px;margin-bottom:16px;">
                                <p style="margin:0 0 8px 0;font-weight:bold;">🎧 Audio Player — use ▶ Jump To buttons below to skip to coaching moments</p>
                                <audio id="{player_id}" controls style="width:100%;">
                                    <source src="data:audio/wav;base64,{audio_base64}" type="audio/wav">
                                </audio>
                            </div>""", unsafe_allow_html=True)

                    st.markdown("---")

                    # ============================================================
                    # ACTIVE LISTENING — matches objection format
                    # ============================================================
                    listening_fails = feedback.get('active_listening_failures', [])
                    if listening_fails:
                        st.markdown("### 🎧 Active Listening Coaching")
                        for fi, fail in enumerate(listening_fails):
                            customer_said = fail.get('customer_said', '')
                            st.markdown(f"#### 📍 Moment {fi+1}: **\"{customer_said[:80]}{'...' if len(customer_said)>80 else ''}\"**")

                            what_was_missed = fail.get('what_was_missed', '')
                            if what_was_missed:
                                st.info(f"🎯 **The Real Miss:** {what_was_missed}")

                            st.caption(f"⏱ Timestamp: {fail.get('timestamp','N/A')} | 🎓 {fail.get('framework_connection','')}")
                            make_jump_button(player_id, fail.get('timestamp', '00:00'), audio_available)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**💬 What Was Said:**")
                                st.info(f"**Customer:** \"{fail.get('customer_said','')}\"")
                                st.warning(f"**Rep:** \"{fail.get('rep_response','')}\"")
                                attempted = fail.get('what_rep_attempted', '')
                                worked = fail.get('what_worked', '')
                                if attempted and attempted.lower() not in ['none', '']:
                                    st.success(f"✓ **Rep attempted:** {attempted}")
                                if worked and worked.lower() not in ['none', '']:
                                    st.success(f"✓ **What worked:** {worked}")

                            with col2:
                                st.markdown("**💡 Step-by-Step Better Approach:**")
                                why = fail.get('why_it_matters', '')
                                better = fail.get('better_response', '')
                                st.markdown("**Step 1: Mirror & Acknowledge**")
                                if why:
                                    st.caption(f"📖 {why}")
                                st.markdown("**Step 2: Say This Instead**")
                                if better:
                                    st.success(f'💬 "{better}"')

                            st.markdown("---")

                    # ============================================================
                    # MISSED PROBING — matches objection format
                    # ============================================================
                    probing_misses = feedback.get('missed_probing_opportunities', [])
                    if probing_misses:
                        st.markdown("### 🔍 Missed Probing Opportunities")
                        for pi, miss in enumerate(probing_misses):
                            surface = miss.get('surface_answer', '')
                            st.markdown(f"#### 📍 Opportunity {pi+1}: **\"{surface[:80]}{'...' if len(surface)>80 else ''}\"**")

                            why_hurts = miss.get('why_stopping_hurts', '')
                            if why_hurts:
                                st.info(f"🎯 **What Was Left on the Table:** {why_hurts}")

                            st.caption(f"⏱ Timestamp: {miss.get('timestamp','N/A')} | 🎓 {miss.get('framework_connection','')}")
                            make_jump_button(player_id, miss.get('timestamp', '00:00'), audio_available)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**💬 What Happened:**")
                                st.info(f"**Customer said:** \"{surface}\"")
                                attempted = miss.get('rep_attempted', '')
                                worked = miss.get('what_worked', '')
                                did_instead = miss.get('what_rep_did_instead', '')
                                if attempted and attempted.lower() not in ['none', '']:
                                    st.warning(f"**Rep asked:** \"{attempted}\"")
                                if worked and worked.lower() not in ['none', '']:
                                    st.success(f"✓ **What worked:** {worked}")
                                if did_instead:
                                    st.error(f"**Then rep:** {did_instead}")

                            with col2:
                                st.markdown("**💡 Step-by-Step Better Approach:**")
                                should_ask = miss.get('should_have_asked', '')
                                why_works = miss.get('why_this_question_works', '')
                                st.markdown("**Step 1: Don't stop — ask the follow-up**")
                                if should_ask:
                                    st.success(f'💬 "{should_ask}"')
                                if why_works:
                                    st.caption(f"📖 {why_works}")
                                st.markdown("**Step 2: Sit with the answer — then dig one more level**")
                                st.info("Ask: 'Tell me more about that...' or 'What does that mean for you?'")

                            st.markdown("---")

                    # ============================================================
                    # EMOTIONAL CUES — matches objection format
                    # ============================================================
                    emotional_misses = feedback.get('emotional_cues_missed', [])
                    if emotional_misses:
                        st.markdown("### 💭 Emotional Cues Missed")
                        emotion_icons = {"frustration": "😤", "hesitation": "🤔", "excitement": "😊",
                                         "concern": "😟", "doubt": "🤨", "fear": "😰", "distrust": "🤐",
                                         "pain": "😣", "relief": "😌", "urgency": "⏰", "shame": "😔", "overwhelm": "😩"}

                        for ei, miss in enumerate(emotional_misses):
                            emotion = miss.get('customer_emotion', '')
                            signal = miss.get('signal', '')
                            ack_level = miss.get('rep_acknowledgment_level', 'none')
                            icon = emotion_icons.get(emotion, "💭")

                            st.markdown(f"#### {icon} Missed {emotion.title()}: **\"{signal[:80]}{'...' if len(signal)>80 else ''}\"**")

                            real_miss = miss.get('rep_missed_it', '')
                            if real_miss:
                                st.info(f"🎯 **The Real Miss:** {real_miss}")

                            ack_labels = {"none": "❌ Rep did not acknowledge this emotion", "partial": "⚠️ Rep partially acknowledged — good start, needs more", "full": "✅ Rep fully acknowledged"}
                            if ack_level == "full":
                                st.success(ack_labels[ack_level])
                            elif ack_level == "partial":
                                st.warning(ack_labels[ack_level])
                            else:
                                st.error(ack_labels.get(ack_level, ack_level))

                            st.caption(f"⏱ Timestamp: {miss.get('timestamp','N/A')} | 🎓 {miss.get('framework_connection','')}")
                            make_jump_button(player_id, miss.get('timestamp', '00:00'), audio_available)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**💬 What Was Said:**")
                                st.info(f"**Emotional signal:** {signal}")
                                attempted = miss.get('rep_attempted', '')
                                worked = miss.get('what_worked', '')
                                why_matters = miss.get('why_it_matters', '')
                                if attempted and attempted.lower() not in ['none', '']:
                                    st.warning(f"**Rep said:** \"{attempted}\"")
                                if worked and worked.lower() not in ['none', '']:
                                    st.success(f"✓ **What worked:** {worked}")
                                if why_matters:
                                    st.error(f"⚠️ **Why this moment matters:** {why_matters}")

                            with col2:
                                st.markdown("**💡 Step-by-Step Better Approach:**")
                                empathy = miss.get('empathy_response', '')
                                st.markdown("**Step 1: Name the emotion specifically**")
                                st.info("Generic empathy = 'I understand.' | Targeted empathy = naming exactly what they felt.")
                                st.markdown("**Step 2: Say this instead**")
                                if empathy:
                                    st.success(f'💬 "{empathy}"')

                            st.markdown("---")

                    # ============================================================
                    # OBJECTION HANDLING (unchanged — already excellent format)
                    # ============================================================
                    objections = feedback.get('objection_handling_analysis', [])
                    if objections:
                        st.markdown("### 🛡️ Objection Handling Analysis")
                        for oi, obj in enumerate(objections):
                            effectiveness = obj.get('effectiveness_rating', 0)
                            color = "🟢" if effectiveness >= 7 else "🟡" if effectiveness >= 4 else "🔴"
                            st.markdown(f"#### {color} Objection {oi+1}: \"{obj.get('objection', '')}\"")
                            st.caption(f"Effectiveness: {effectiveness}/10 | Timestamp: {obj.get('timestamp','N/A')}")

                            st.info(f"🎯 **The Real Objection:** {obj.get('real_objection','')}")

                            make_jump_button(player_id, obj.get('timestamp', '00:00'), audio_available)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("**💬 What Was Said:**")
                                st.warning(f"**Rep's response:** \"{obj.get('rep_response','')}\"")
                                attempted = obj.get('rep_attempted', '')
                                worked = obj.get('what_worked', '')
                                if attempted and attempted.lower() not in ['none', '']:
                                    st.info(f"**Rep attempted:** {attempted}")
                                if worked and worked.lower() not in ['none', 'nothing']:
                                    st.success(f"✓ **What worked:** {worked}")

                            with col2:
                                st.markdown("**❌ Critical Failures:**")
                                for failure in obj.get('critical_failures', []):
                                    st.error(f"• {failure}")
                                if obj.get('went_straight_to_discount'):
                                    st.error("💰 **Jumped straight to discount!**")
                                if not obj.get('value_established'):
                                    st.error("⚠️ **Value was NOT established first**")

                            st.markdown("**💡 Step-by-Step Better Approach:**")
                            for step in obj.get('step_by_step_better_approach', []):
                                st.markdown(f"**Step {step.get('step','')}: {step.get('action','')}**")
                                st.success(f"💬 \"{step.get('example','')}\"")
                                if step.get('why'):
                                    st.caption(f"📖 {step.get('why','')}")
                                st.markdown("")

                            col1, col2 = st.columns(2)
                            with col1:
                                if obj.get('sandler_technique_recommended'):
                                    st.info(f"**Sandler Technique:** {obj.get('sandler_technique_recommended','')}")
                                if obj.get('why_this_technique'):
                                    st.caption(f"💡 {obj.get('why_this_technique','')}")
                            with col2:
                                if obj.get('framework_connections'):
                                    st.info(f"**Framework:** {obj.get('framework_connections','')}")
                            st.markdown("---")

                    # ============================================================
                    # WHAT WENT WELL + OPPORTUNITIES
                    # ============================================================
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("### 💚 What Went Well")
                        went_well = feedback.get('what_went_well', [])
                        if went_well:
                            for item in went_well:
                                render_what_went_well_item(item)
                        else:
                            st.info("Building feedback...")

                    with col2:
                        st.markdown("### 📈 Opportunities to Improve")
                        opportunities = feedback.get('opportunities_to_improve', [])
                        if opportunities:
                            for item in opportunities:
                                text = item if isinstance(item, str) else str(item)
                                st.warning(f"⚠️ {text}")
                        else:
                            st.info("Building feedback...")

                    # Sample Phrases
                    phrases = feedback.get('sample_phrases', {})
                    if phrases:
                        st.markdown("### 💬 Sample Phrases to Practice")
                        phrase_col1, phrase_col2 = st.columns(2)
                        with phrase_col1:
                            for key, label in [('active_listening', '🎧 Active Listening'), ('probing_deeper', '🔍 Probing Deeper'),
                                               ('emotional_acknowledgment', '💭 Emotional Acknowledgment'), ('assumptive_closing', '🎯 Assumptive Closing')]:
                                if phrases.get(key):
                                    with st.expander(label):
                                        for phrase in phrases[key]:
                                            st.markdown(f"- _{phrase}_")
                        with phrase_col2:
                            for key, label in [('spin_implication', '🎯 SPIN Implication (Build Value!)'),
                                               ('sandler_pain', '💼 Sandler Pain Questions'),
                                               ('chemicals_disclosure', '🧪 Chemicals Disclosure'),
                                               ('value_reinforcement', '💰 Value Reinforcement')]:
                                if phrases.get(key):
                                    with st.expander(label):
                                        for phrase in phrases[key]:
                                            st.markdown(f"- _{phrase}_")

                    with st.expander("📄 Full Transcript"):
                        st.text(row.get('transcript', ''))

# ===== TAB 2: EXCEPTIONAL MOMENTS =====
with tab2:
    st.header("🌟 Exceptional Moments Feed")
    st.caption("Share these wins with your team! 🔥")

    exceptional_calls = []
    for idx, row in df.iterrows():
        feedback = row['feedback_parsed']
        if feedback:
            shareworthy = [m for m in feedback.get('exceptional_moments', []) if m.get('shareworthy')]
            if shareworthy:
                exceptional_calls.append({'idx': idx, 'row': row, 'moments': shareworthy})

    if not exceptional_calls:
        st.info("No exceptional moments yet — keep coaching!")
    else:
        for call in exceptional_calls:
            row = call['row']
            with st.expander(f"⭐ {row['agent_name']} — {row['filename']} ({row['date']})"):
                st.write(f"**Agent:** {row['agent_name']}")
                st.write(f"**Outcome:** {row['feedback_parsed'].get('call_outcome','unknown').upper()}")
                st.markdown("---")
                for moment in call['moments']:
                    cat = moment.get('category', 'general')
                    cat_icons = {'objection_handling': '🛡️', 'empathy': '❤️', 'active_listening': '🎧', 'probing': '🔍', 'assumptive_selling': '🎯', 'closing': '✅'}
                    icon = cat_icons.get(cat, '⭐')
                    st.markdown(f"### {icon} {cat.replace('_',' ').title()}")
                    st.markdown(f"**⏱ Timestamp: {moment.get('timestamp','N/A')}**")

                    # Show full exchange if available
                    full_exchange = moment.get('full_exchange', [])
                    if full_exchange:
                        st.markdown("**📞 The Full Exchange:**")
                        for line in full_exchange:
                            speaker = line.get('speaker', '').title()
                            text = line.get('text', '')
                            if speaker == 'Customer':
                                st.info(f"**Customer:** \"{text}\"")
                            else:
                                st.success(f"**Rep:** \"{text}\"")
                    else:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.info(f"**Customer:** \"{moment.get('customer_quote','N/A')}\"")
                            st.success(f"**Rep:** \"{moment.get('rep_quote','N/A')}\"")
                        with col2:
                            st.write(f"**What happened:** {moment.get('what_happened','N/A')}")
                            st.success(f"**Why exceptional:** {moment.get('why_exceptional','N/A')}")
                            if moment.get('coaching_insight'):
                                st.info(f"**Framework:** {moment.get('coaching_insight','')}")
                    st.markdown("---")

# ===== TAB 3: TEAM ANALYTICS =====
with tab3:
    st.header("📊 Team Analytics Dashboard")

    outcomes, all_scores = [], []
    for _, row in df.iterrows():
        feedback = row['feedback_parsed']
        if feedback:
            if feedback.get('call_outcome'):
                outcomes.append(feedback['call_outcome'])
            overall = feedback.get('call_score', {}).get('overall_score', 0)
            if overall > 0:
                all_scores.append(overall)

    closed = outcomes.count('closed')
    lost = outcomes.count('lost')
    total_outcomes = closed + lost
    close_rate = (closed / total_outcomes * 100) if total_outcomes > 0 else 0
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Total Calls", len(df))
    with col2: st.metric("Team Close Rate", f"{close_rate:.1f}%")
    with col3: st.metric("Avg Score", f"{avg_score:.1f}/10")
    with col4: st.metric("Team W/L", f"{closed}/{lost}")

    st.markdown("---")
    st.subheader("🏆 Agent Leaderboard")

    agent_stats = {}
    for _, row in df.iterrows():
        agent = row['agent_name']
        if pd.isna(agent):
            continue
        if agent not in agent_stats:
            agent_stats[agent] = {'calls': 0, 'closed': 0, 'lost': 0, 'scores': []}
        agent_stats[agent]['calls'] += 1
        feedback = row['feedback_parsed']
        if feedback:
            outcome = feedback.get('call_outcome', '')
            if outcome == 'closed':
                agent_stats[agent]['closed'] += 1
            elif outcome == 'lost':
                agent_stats[agent]['lost'] += 1
            overall = feedback.get('call_score', {}).get('overall_score', 0)
            if overall > 0:
                agent_stats[agent]['scores'].append(overall)

    leaderboard = []
    for agent, stats in agent_stats.items():
        total = stats['closed'] + stats['lost']
        cr = (stats['closed'] / total * 100) if total > 0 else 0
        avg = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0
        leaderboard.append({'Agent': agent, 'Calls': stats['calls'], 'Close Rate': f"{cr:.1f}%",
                             'Avg Score': f"{avg:.1f}/10", 'Closed': stats['closed'], 'Lost': stats['lost']})

    if leaderboard:
        st.dataframe(pd.DataFrame(leaderboard).sort_values('Close Rate', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Not enough data yet")

# ===== TAB 4: CALL SEARCH =====
with tab4:
    st.header("🔍 Advanced Call Search")
    search_type = st.selectbox("Search By:", ["Keyword", "Customer Intent", "Outcome"])

    if search_type == "Keyword":
        keyword = st.text_input("Search transcripts for:")
        if keyword:
            matches = [row for _, row in df.iterrows() if keyword.lower() in str(row.get('transcript', '')).lower()]
            st.write(f"Found **{len(matches)}** calls mentioning '{keyword}'")
            for row in matches:
                with st.expander(f"📞 {row['agent_name']} — {row['filename']}"):
                    feedback = row['feedback_parsed']
                    if feedback:
                        st.write(f"**Summary:** {feedback.get('summary','')}")
                    st.write(f"**Excerpt:** {str(row.get('transcript',''))[:300]}...")

st.sidebar.markdown("---")
st.sidebar.caption("🎓 Powered by SPIN + Sandler")

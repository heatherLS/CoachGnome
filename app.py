import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import base64
import requests

# ---------- CONFIG ----------
st.set_page_config(page_title="🧙‍♂️ CoachGnome – AI Call Coach", layout="wide")

# Google Sheets URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/1pKtkFr5x4_RRj-ruXnLZl3D4_IBzkyOnynWjjPac0jo/export?format=csv"

# ---------- AUDIO DOWNLOAD ----------
@st.cache_data(ttl=3600)
def download_audio_from_gdrive(drive_url, filename):
    """Download audio from Google Drive and return as base64"""
    file_id = None
    if "id=" in drive_url:
        file_id = drive_url.split("id=")[1].split("&")[0]
    elif "/d/" in drive_url:
        file_id = drive_url.split("/d/")[1].split("/")[0]
    
    if not file_id:
        return None
    
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    max_retries = 3
    timeouts = [60, 90, 120]
    
    for attempt in range(max_retries):
        try:
            timeout = timeouts[attempt]
            session = requests.Session()
            response = session.get(download_url, stream=True, timeout=timeout)
            
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    params = {'confirm': value, 'id': file_id}
                    response = session.get(download_url, params=params, stream=True, timeout=timeout)
                    break
            
            audio_bytes = b''
            chunk_size = 8192
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    audio_bytes += chunk
            
            audio_base64 = base64.b64encode(audio_bytes).decode()
            return audio_base64
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                st.warning(f"Download timed out, retrying... (attempt {attempt + 2}/{max_retries})")
                continue
            else:
                st.error(f"Failed to download audio after {max_retries} attempts.")
                return None
        except Exception as e:
            st.error(f"Error downloading audio: {e}")
            return None
    
    return None

# ---------- LOAD DATA ----------
@st.cache_data(ttl=60)
def load_data():
    """Load data from Google Sheets"""
    try:
        df = pd.read_csv(SHEET_URL)
        df['feedback_parsed'] = df['feedback_json'].apply(parse_feedback)
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

def parse_feedback(feedback_str):
    """Parse feedback JSON string"""
    if pd.isna(feedback_str) or not feedback_str:
        return {}
    try:
        clean_str = feedback_str.strip()
        if clean_str.startswith('```'):
            clean_str = clean_str.split('```')[1]
            if clean_str.startswith('json'):
                clean_str = clean_str[4:]
        clean_str = clean_str.strip()
        return json.loads(clean_str)
    except:
        return {}

def filter_by_time_period(df, time_filter):
    """Filter dataframe by selected time period"""
    if df.empty or 'date' not in df.columns:
        return df
    
    # Convert date column to datetime if it isn't already
    try:
        df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    except:
        return df  # If date parsing fails, return unfiltered
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if time_filter == "Today":
        filtered = df[df['date_parsed'] >= today_start]
    elif time_filter == "This Week":
        week_start = today_start - timedelta(days=today_start.weekday())
        filtered = df[df['date_parsed'] >= week_start]
    elif time_filter == "This Month":
        month_start = today_start.replace(day=1)
        filtered = df[df['date_parsed'] >= month_start]
    else:  # All Time
        filtered = df
    
    return filtered

def aggregate_rep_performance(df, agent_name):
    """Aggregate all performance data for a specific rep"""
    agent_calls = df[df['agent_name'] == agent_name]
    
    aggregated = {
        'total_calls': len(agent_calls),
        'outcomes': {'closed': 0, 'lost': 0, 'follow_up': 0},
        'scores': {
            'overall': [],
            'active_listening': [],
            'probing_depth': [],
            'emotional_intelligence': [],
            'value_based_selling': [],
            'spin_effectiveness': [],
            'sandler_effectiveness': [],
            'objection_handling': []
        },
        'common_strengths': [],
        'common_weaknesses': [],
        'active_listening_patterns': [],
        'probing_patterns': [],
        'emotional_cue_patterns': [],
        'objection_patterns': [],
        'spin_gaps': {
            'situation': 0,
            'problem': 0,
            'implication': 0,
            'need_payoff': 0
        },
        'sandler_gaps': {
            'upfront_contract': 0,
            'pain_depth_surface': 0,
            'budget_qualified': 0,
            'decision_process': 0
        }
    }
    
    for _, row in agent_calls.iterrows():
        feedback = row['feedback_parsed']
        if not feedback:
            continue
        
        # Outcomes
        outcome = feedback.get('call_outcome', '')
        if outcome == 'closed':
            aggregated['outcomes']['closed'] += 1
        elif outcome == 'lost':
            aggregated['outcomes']['lost'] += 1
        elif outcome in ['follow-up-scheduled', 'needs-callback']:
            aggregated['outcomes']['follow_up'] += 1
        
        # Scores
        call_scores = feedback.get('call_score', {})
        for score_type in aggregated['scores'].keys():
            score_value = call_scores.get(score_type, 0)
            if score_value > 0:
                aggregated['scores'][score_type].append(score_value)
        
        # Strengths and weaknesses
        aggregated['common_strengths'].extend(feedback.get('what_went_well', []))
        aggregated['common_weaknesses'].extend(feedback.get('opportunities_to_improve', []))
        
        # Active listening failures
        listening_fails = feedback.get('active_listening_failures', [])
        for fail in listening_fails:
            aggregated['active_listening_patterns'].append({
                'what_was_missed': fail.get('what_was_missed', ''),
                'date': row['date'],
                'filename': row['filename']
            })
        
        # Probing opportunities
        probing_misses = feedback.get('missed_probing_opportunities', [])
        for miss in probing_misses:
            aggregated['probing_patterns'].append({
                'pattern': 'Stopped at surface level',
                'date': row['date'],
                'filename': row['filename']
            })
        
        # Emotional cues
        emotional_misses = feedback.get('emotional_cues_missed', [])
        for miss in emotional_misses:
            aggregated['emotional_cue_patterns'].append({
                'emotion': miss.get('customer_emotion', ''),
                'date': row['date'],
                'filename': row['filename']
            })
        
        # Objections
        objections = feedback.get('objection_handling_analysis', [])
        for obj in objections:
            aggregated['objection_patterns'].append({
                'objection': obj.get('objection', ''),
                'effectiveness': obj.get('effectiveness_rating', 0),
                'went_to_discount': obj.get('went_straight_to_discount', False),
                'date': row['date'],
                'filename': row['filename']
            })
        
        # SPIN gaps
        spin = feedback.get('spin_analysis', {})
        if not spin.get('situation_questions_used'):
            aggregated['spin_gaps']['situation'] += 1
        if not spin.get('problem_questions_used'):
            aggregated['spin_gaps']['problem'] += 1
        if not spin.get('implication_questions_used'):
            aggregated['spin_gaps']['implication'] += 1
        if not spin.get('need_payoff_questions_used'):
            aggregated['spin_gaps']['need_payoff'] += 1
        
        # Sandler gaps
        sandler = feedback.get('sandler_analysis', {})
        if not sandler.get('upfront_contract_established'):
            aggregated['sandler_gaps']['upfront_contract'] += 1
        if sandler.get('pain_depth') == 'surface':
            aggregated['sandler_gaps']['pain_depth_surface'] += 1
        if not sandler.get('budget_qualified'):
            aggregated['sandler_gaps']['budget_qualified'] += 1
        if not sandler.get('decision_process_identified'):
            aggregated['sandler_gaps']['decision_process'] += 1
    
    return aggregated

# ---------- PAGE ----------
st.title("🧙‍♂️ CoachGnome – AI Call Coach Dashboard")
st.caption("Powered by SPIN Selling + Sandler Methodology ✨")

# Sidebar controls
with st.sidebar:
    st.header("📊 Dashboard Controls")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        # Clear session state to force reload
        if 'filtered_df' in st.session_state:
            del st.session_state['filtered_df']
        st.rerun()
    
    date_filter = st.selectbox(
        "Time Period",
        ["Today", "This Week", "This Month", "All Time"],
        key="time_filter"
    )
    
    st.markdown("---")
    st.caption("💾 Data synced from Google Sheets")
    st.caption("🎓 Coaching analysis by GPT-4")

# Load data ONCE and cache it
raw_df = load_data()

if raw_df.empty:
    st.warning("No data available yet. Upload call recordings to start!")
    st.stop()

# Apply time filter - this runs on filter change
df = filter_by_time_period(raw_df, date_filter)

# Show count in sidebar
with st.sidebar:
    st.caption(f"📞 Showing {len(df)} of {len(raw_df)} calls")

# Handle empty filtered results
if df.empty and date_filter != "All Time":
    st.info(f"No calls found for '{date_filter}'. Try a different time period or check back later!")
    st.stop()

# ---------- TABS ----------
tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Executive Summary",
    "🏆 Rep Deep Dive", 
    "🌟 Exceptional Moments",
    "📊 Team Analytics",
    "🔍 Call Search"
])

# ===== TAB 0: EXECUTIVE SUMMARY =====
with tab0:
    st.header("📋 Executive Summary - Quick Coaching Priorities")
    st.caption("What needs immediate attention across the team")
    
    # [EXECUTIVE SUMMARY CODE - keeping as is from your original]
    all_agents = df['agent_name'].dropna().unique()
    
    team_issues = {
        'active_listening': [],
        'probing': [],
        'emotional_cues': [],
        'objections': [],
        'went_to_discount': []
    }
    
    agent_performance = {}
    
    for agent in all_agents:
        agent_calls = df[df['agent_name'] == agent]
        
        agent_performance[agent] = {
            'total_calls': len(agent_calls),
            'listening_fails': 0,
            'probing_fails': 0,
            'emotional_fails': 0,
            'objection_fails': 0,
            'discount_count': 0,
            'exceptional_count': 0,
            'avg_score': 0,
            'scores': []
        }
        
        for _, row in agent_calls.iterrows():
            feedback = row['feedback_parsed']
            if not feedback:
                continue
            
            listening = len(feedback.get('active_listening_failures', []))
            probing = len(feedback.get('missed_probing_opportunities', []))
            emotional = len(feedback.get('emotional_cues_missed', []))
            objections = feedback.get('objection_handling_analysis', [])
            
            agent_performance[agent]['listening_fails'] += listening
            agent_performance[agent]['probing_fails'] += probing
            agent_performance[agent]['emotional_fails'] += emotional
            agent_performance[agent]['objection_fails'] += len(objections)
            
            for obj in objections:
                if obj.get('went_straight_to_discount'):
                    agent_performance[agent]['discount_count'] += 1
                    team_issues['went_to_discount'].append(agent)
            
            exceptional = feedback.get('exceptional_moments', [])
            shareworthy = [m for m in exceptional if m.get('shareworthy')]
            agent_performance[agent]['exceptional_count'] += len(shareworthy)
            
            scores = feedback.get('call_score', {})
            if scores and isinstance(scores, dict):
                overall = scores.get('overall_score', 0)
                if overall > 0:
                    agent_performance[agent]['scores'].append(overall)
        
        if agent_performance[agent]['scores']:
            agent_performance[agent]['avg_score'] = sum(agent_performance[agent]['scores']) / len(agent_performance[agent]['scores'])
    
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
            
            st.info("**Quick Training Tip:** Practice the 'Mirror & Build' technique - repeat back what the customer said, then ask a follow-up question.")
        else:
            st.success("✓ Team performing well!")
    
    with col2:
        st.markdown("### 🔍 Probing Depth")
        if struggling_probing and struggling_probing[0][1] > 0:
            st.warning("**Needs Focus:**")
            for agent, count in struggling_probing:
                if count > 0:
                    st.write(f"- **{agent}**: {count} missed opportunities")
            
            st.info("**Quick Training Tip:** Use the 'Why → What → How' ladder. Never accept the first answer - dig at least 2 levels deeper.")
        else:
            st.success("✓ Team digging deep!")
    
    with col3:
        st.markdown("### 💰 Discount Jumping")
        if struggling_discount and struggling_discount[0][1] > 0:
            st.error("**Critical Issue:**")
            for agent, count in struggling_discount:
                if count > 0:
                    st.write(f"- **{agent}**: {count} times")
            
            st.info("**Quick Training Tip:** Before ANY discount, ask: 'What happens if you don't solve this problem?' Establish the cost of inaction first.")
        else:
            st.success("✓ Value-selling strong!")
    
    st.markdown("---")
    
    st.subheader("🏆 Performance Tiers")
    
    top_performers = []
    developing = []
    needs_support = []
    
    for agent, perf in agent_performance.items():
        if perf['avg_score'] >= 7:
            top_performers.append((agent, perf))
        elif perf['avg_score'] >= 5:
            developing.append((agent, perf))
        else:
            needs_support.append((agent, perf))
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### 🥇 Top Performers (7+)")
        if top_performers:
            for agent, perf in sorted(top_performers, key=lambda x: x[1]['avg_score'], reverse=True):
                st.success(f"**{agent}**: {perf['avg_score']:.1f}/10")
                if perf['exceptional_count'] > 0:
                    st.caption(f"✨ {perf['exceptional_count']} exceptional moments")
        else:
            st.info("No agents in this tier yet")
    
    with col2:
        st.markdown("### 📈 Developing (5-6.9)")
        if developing:
            for agent, perf in sorted(developing, key=lambda x: x[1]['avg_score'], reverse=True):
                st.warning(f"**{agent}**: {perf['avg_score']:.1f}/10")
        else:
            st.info("No agents in this tier")
    
    with col3:
        st.markdown("### 🆘 Needs Support (<5)")
        if needs_support:
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
        else:
            st.success("No agents need urgent support")
    
    st.markdown("---")
    
    st.subheader("✨ Skill Spotlight - Learn from the Best")
    
    exceptional_by_category = {
        'objection_handling': {},
        'empathy': {},
        'active_listening': {},
        'probing': {}
    }
    
    for _, row in df.iterrows():
        feedback = row['feedback_parsed']
        if not feedback:
            continue
        
        agent = row['agent_name']
        exceptional = feedback.get('exceptional_moments', [])
        
        for moment in exceptional:
            if moment.get('shareworthy'):
                category = moment.get('category', 'general')
                if category in exceptional_by_category:
                    if agent not in exceptional_by_category[category]:
                        exceptional_by_category[category][agent] = 0
                    exceptional_by_category[category][agent] += 1
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🛡️ Objection Handling Champions")
        if exceptional_by_category['objection_handling']:
            top_objection = sorted(exceptional_by_category['objection_handling'].items(), key=lambda x: x[1], reverse=True)[:3]
            for agent, count in top_objection:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")
        
        st.markdown("### 🔍 Probing Masters")
        if exceptional_by_category['probing']:
            top_probing = sorted(exceptional_by_category['probing'].items(), key=lambda x: x[1], reverse=True)[:3]
            for agent, count in top_probing:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")
    
    with col2:
        st.markdown("### ❤️ Empathy Experts")
        if exceptional_by_category['empathy']:
            top_empathy = sorted(exceptional_by_category['empathy'].items(), key=lambda x: x[1], reverse=True)[:3]
            for agent, count in top_empathy:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")
        
        st.markdown("### 🎧 Active Listening Leaders")
        if exceptional_by_category['active_listening']:
            top_listening = sorted(exceptional_by_category['active_listening'].items(), key=lambda x: x[1], reverse=True)[:3]
            for agent, count in top_listening:
                st.success(f"🏆 **{agent}**: {count} exceptional moments")
        else:
            st.info("Building data...")
    
    st.markdown("---")
    
    st.subheader("⚡ Recommended Actions")
    
    actions = []
    
    total_listening_fails = sum(p['listening_fails'] for p in agent_performance.values())
    total_probing_fails = sum(p['probing_fails'] for p in agent_performance.values())
    total_discount_jumps = sum(p['discount_count'] for p in agent_performance.values())
    
    if total_listening_fails > len(df) * 0.3:
        actions.append("🚨 **Team Training Needed:** Active Listening workshop - over 30% of calls show listening failures")
    
    if total_probing_fails > len(df) * 0.4:
        actions.append("⚠️ **Team Training Needed:** SPIN Selling refresher - agents stopping at surface answers")
    
    if total_discount_jumps > len(df) * 0.2:
        actions.append("🔴 **Urgent:** Value-based selling training - too many reps jumping to discounts")
    
    if needs_support:
        for agent, perf in needs_support:
            actions.append(f"👤 **1-on-1 Coaching:** {agent} needs immediate support (score: {perf['avg_score']:.1f})")
    
    if actions:
        for action in actions:
            st.warning(action)
    else:
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
        
        st.subheader(f"📈 {selected_agent} - Overall Performance")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Calls", agg_data['total_calls'])
        
        with col2:
            total_outcomes = agg_data['outcomes']['closed'] + agg_data['outcomes']['lost']
            close_rate = (agg_data['outcomes']['closed'] / total_outcomes * 100) if total_outcomes > 0 else 0
            st.metric("Close Rate", f"{close_rate:.1f}%")
        
        with col3:
            avg_overall = sum(agg_data['scores']['overall']) / len(agg_data['scores']['overall']) if agg_data['scores']['overall'] else 0
            st.metric("Avg Score", f"{avg_overall:.1f}/10")
        
        with col4:
            st.metric("W/L Record", f"{agg_data['outcomes']['closed']}/{agg_data['outcomes']['lost']}")
        
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
                scores = agg_data['scores'][key]
                avg = sum(scores) / len(scores) if scores else 0
                st.metric(label, f"{avg:.1f}/10")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🚨 Critical Patterns to Address")
            
            if agg_data['active_listening_patterns']:
                with st.expander(f"🎧 Active Listening Issues ({len(agg_data['active_listening_patterns'])} instances)", expanded=True):
                    patterns = {}
                    for pattern in agg_data['active_listening_patterns']:
                        issue = pattern['what_was_missed']
                        if issue not in patterns:
                            patterns[issue] = 0
                        patterns[issue] += 1
                    
                    sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]
                    for issue, count in sorted_patterns:
                        st.error(f"**{count}x**: {issue}")
            
            if agg_data['probing_patterns']:
                with st.expander(f"🔍 Probing Issues ({len(agg_data['probing_patterns'])} instances)"):
                    st.warning(f"Stopped at surface level **{len(agg_data['probing_patterns'])} times** across calls")
                    st.write("**Pattern:** Not digging deeper after initial answers")
            
            if agg_data['emotional_cue_patterns']:
                with st.expander(f"💭 Emotional Cues Missed ({len(agg_data['emotional_cue_patterns'])} instances)"):
                    emotions = {}
                    for pattern in agg_data['emotional_cue_patterns']:
                        emotion = pattern['emotion']
                        if emotion not in emotions:
                            emotions[emotion] = 0
                        emotions[emotion] += 1
                    
                    for emotion, count in sorted(emotions.items(), key=lambda x: x[1], reverse=True):
                        st.warning(f"**{emotion.title()}**: {count}x")
        
        with col2:
            st.subheader("🎓 Framework Gaps")
            
            with st.expander("🎯 SPIN Selling Gaps", expanded=True):
                spin_total = agg_data['total_calls']
                
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
                    avg_effectiveness = sum(o['effectiveness'] for o in agg_data['objection_patterns']) / len(agg_data['objection_patterns'])
                    
                    if went_to_discount > 0:
                        st.error(f"⚠️ Went straight to discount **{went_to_discount} times**")
                    
                    st.write(f"**Avg Effectiveness**: {avg_effectiveness:.1f}/10")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("💪 Common Strengths")
            if agg_data['common_strengths']:
                strength_counts = {}
                for strength in agg_data['common_strengths']:
                    # Convert to string if it's a dict or other type
                    if isinstance(strength, dict):
                        strength_text = strength.get('text', str(strength))
                    else:
                        strength_text = str(strength)
                    
                    if strength_text not in strength_counts:
                        strength_counts[strength_text] = 0
                    strength_counts[strength_text] += 1
                
                top_strengths = sorted(strength_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                for strength, count in top_strengths:
                    st.success(f"✓ {strength} ({count} calls)")
            else:
                st.info("Building performance history...")
        
        with col2:
            st.subheader("📈 Top Growth Areas")
            if agg_data['common_weaknesses']:
                weakness_counts = {}
                for weakness in agg_data['common_weaknesses']:
                    # Convert to string if it's a dict or other type
                    if isinstance(weakness, dict):
                        weakness_text = weakness.get('text', str(weakness))
                    else:
                        weakness_text = str(weakness)
                    
                    if weakness_text not in weakness_counts:
                        weakness_counts[weakness_text] = 0
                    weakness_counts[weakness_text] += 1
                
                top_weaknesses = sorted(weakness_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                for weakness, count in top_weaknesses:
                    st.warning(f"⚠️ {weakness} ({count} calls)")
            else:
                st.info("Building performance history...")
        
        st.markdown("---")
        
        st.subheader(f"📞 All Calls with Enhanced Coaching ({agg_data['total_calls']})")
        
        agent_calls = df[df['agent_name'] == selected_agent]
        
        for idx, row in agent_calls.iterrows():
            feedback = row['feedback_parsed']
            outcome = feedback.get('call_outcome', 'unknown') if feedback else 'unknown'
            
            outcome_icons = {
                "closed": "🟢",
                "lost": "🔴",
                "follow-up-scheduled": "🟡",
                "needs-callback": "🟠"
            }
            icon = outcome_icons.get(outcome, "⚪")
            
            with st.expander(f"{icon} {row['filename']} - {outcome.upper()} ({row['date']})"):
                if feedback:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.write(f"**Summary:** {feedback.get('summary', '')}")
                        st.write(f"**Customer Intent:** {feedback.get('customer_intent', '')}")
                    with col2:
                        scores = feedback.get('call_score', {})
                        if scores:
                            st.write(f"**Overall Score:** {scores.get('overall_score', 0)}/10")
                        st.write(f"**Close Reason:** {feedback.get('close_reason', '')}")
                    with col3:
                        disposition = row.get('disposition', 'Unknown')
                        if pd.notna(disposition):
                            st.write(f"**Five9 Disposition:** {disposition}")
                            if 'credit card' in str(disposition).lower():
                                st.success("💳 Reached Credit Card Stage!")
                        st.write(f"**Call Duration:** {row.get('call_duration', 'N/A')}s")
                    
                    st.markdown("---")
                    
                    # ==== LOAD AUDIO PLAYER FIRST ====
                    audio_available = False
                    player_id = None
                    
                    if pd.notna(row.get('audio_url')) and row.get('audio_url'):
                        audio_available = True
                        google_drive_url = row['audio_url']
                        
                        if 'drive.google.com' in google_drive_url:
                            with st.spinner("🎧 Loading audio player..."):
                                audio_base64 = download_audio_from_gdrive(google_drive_url, row['filename'])
                            
                            if audio_base64:
                                player_id = f"main_audio_{row['filename'].replace(' ', '_').replace('.', '_')}"
                                
                                audio_html = f"""
                                <div style="position: sticky; top: 0; z-index: 1000; background: white; padding: 15px; border: 2px solid #4CAF50; border-radius: 8px; margin-bottom: 20px;">
                                    <p style="margin: 0 0 10px 0; font-weight: bold; color: #333;">
                                        🎧 Master Audio Player - Use timestamp buttons below to jump to specific moments
                                    </p>
                                    <audio id="{player_id}" controls style="width: 100%;">
                                        <source src="data:audio/wav;base64,{audio_base64}" type="audio/wav">
                                    </audio>
                                </div>
                                """
                                
                                st.markdown(audio_html, unsafe_allow_html=True)
                                st.success("✅ Audio loaded! Click '▶ Jump to...' buttons below.")
                    
                    st.markdown("---")
                    
                    st.subheader("🎯 Coaching Breakdown")
                    
                    # === ACTIVE LISTENING ===
                    listening_fails = feedback.get('active_listening_failures', [])
                    if listening_fails:
                        st.markdown("### 🎧 Active Listening - Coaching Moments")
                        
                        for fail_idx, fail in enumerate(listening_fails):
                            st.markdown(f"#### 📍 Moment {fail_idx + 1} - Timestamp: {fail.get('timestamp', 'N/A')}")
                            
                            # Audio jump button
                            if audio_available and player_id:
                                ts = fail.get('timestamp', '00:00')
                                start_seconds = 0
                                try:
                                    if ':' in ts:
                                        parts = ts.split(':')
                                        if len(parts) == 2:
                                            start_seconds = int(parts[0]) * 60 + int(parts[1])
                                        elif len(parts) == 3:
                                            start_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                                    else:
                                        start_seconds = int(float(ts))
                                except:
                                    start_seconds = 0
                                
                                timestamp_button = f"""
                                    <div style="margin-bottom:15px; padding:10px; background:#f0f8ff; border-radius:5px;">
                                        <button onclick="var p = window.parent.document.getElementById('{player_id}'); if (p) {{ p.currentTime = {start_seconds}; p.play(); window.parent.scrollTo({{top: 0, behavior: 'smooth'}}); }}" 
                                        style="padding:10px 20px; background:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">
                                            ▶ Jump to {ts}
                                        </button>
                                    </div>
                                """
                                components.html(timestamp_button, height=80)
                            
                            # Coaching content
                            st.markdown("**🗣️ What Was Said:**")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.info(f"**Customer:** \"{fail.get('customer_said', 'N/A')}\"")
                            with col2:
                                st.warning(f"**Rep:** \"{fail.get('rep_response', 'N/A')}\"")
                            
                            st.markdown("**📊 Coaching Analysis:**")
                            
                            rep_attempted = fail.get('what_rep_attempted', '')
                            if rep_attempted and rep_attempted.lower() not in ['none', 'nothing', '']:
                                st.success(f"**✓ Rep Attempted:** {rep_attempted}")
                            
                            what_worked = fail.get('what_worked', '')
                            if what_worked and what_worked.lower() not in ['none', '']:
                                st.success(f"**✓ What Worked:** {what_worked}")
                            
                            st.error(f"**❌ What Was Missed:** {fail.get('what_was_missed', 'N/A')}")
                            
                            why_matters = fail.get('why_it_matters', '')
                            if why_matters:
                                st.warning(f"**⚠️ Why It Matters:** {why_matters}")
                            
                            st.markdown("**💡 Better Response:**")
                            st.success(f"\"{fail.get('better_response', 'N/A')}\"")
                            
                            framework = fail.get('framework_connection', '')
                            if framework:
                                st.info(f"**🎓 Framework:** {framework}")
                            
                            st.markdown("---")
                    
                    # === PROBING ===
                    probing_misses = feedback.get('missed_probing_opportunities', [])
                    if probing_misses:
                        st.markdown("### 🔍 Missed Probing Opportunities")
                        
                        for probe_idx, miss in enumerate(probing_misses):
                            st.markdown(f"#### 📍 Opportunity {probe_idx + 1} - Timestamp: {miss.get('timestamp', 'N/A')}")
                            
                            # Audio jump button
                            if audio_available and player_id:
                                ts = miss.get('timestamp', '00:00')
                                start_seconds = 0
                                try:
                                    if ':' in ts:
                                        parts = ts.split(':')
                                        if len(parts) == 2:
                                            start_seconds = int(parts[0]) * 60 + int(parts[1])
                                        elif len(parts) == 3:
                                            start_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                                    else:
                                        start_seconds = int(float(ts))
                                except:
                                    start_seconds = 0
                                
                                timestamp_button = f"""
                                    <div style="margin-bottom:15px; padding:10px; background:#f0f8ff; border-radius:5px;">
                                        <button onclick="var p = window.parent.document.getElementById('{player_id}'); if (p) {{ p.currentTime = {start_seconds}; p.play(); window.parent.scrollTo({{top: 0, behavior: 'smooth'}}); }}" 
                                        style="padding:10px 20px; background:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">
                                            ▶ Jump to {ts}
                                        </button>
                                    </div>
                                """
                                components.html(timestamp_button, height=80)
                            
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.markdown("**What Happened:**")
                                st.info(f"**Customer's Surface Answer:** \"{miss.get('surface_answer', 'N/A')}\"")
                                
                                what_did = miss.get('what_rep_did_instead', '')
                                if what_did:
                                    st.warning(f"**Rep Did Instead:** {what_did}")
                                else:
                                    st.warning("**Rep moved on without digging deeper**")
                                
                                why_hurts = miss.get('why_stopping_hurts', '')
                                if why_hurts:
                                    st.error(f"**Cost of Stopping:** {why_hurts}")
                            
                            with col2:
                                st.markdown("**💡 Should Have Asked:**")
                                st.success(f"\"{miss.get('should_have_asked', 'N/A')}\"")
                                
                                why_works = miss.get('why_this_question_works', '')
                                if why_works:
                                    st.info(f"**Why This Works:** {why_works}")
                                
                                framework = miss.get('framework_connection', '')
                                if framework:
                                    st.info(f"**🎓 Framework:** {framework}")
                            
                            st.markdown("---")
                    
                    # === EMOTIONAL CUES ===
                    emotional_misses = feedback.get('emotional_cues_missed', [])
                    if emotional_misses:
                        st.markdown("### 💭 Emotional Cues Missed")
                        emotion_icons = {
                            "frustration": "😤", "hesitation": "🤔", "excitement": "😊",
                            "concern": "😟", "doubt": "🤨", "fear": "😰",
                            "distrust": "🤐", "pain": "😣", "relief": "😌"
                        }
                        
                        for emo_idx, miss in enumerate(emotional_misses):
                            emotion = miss.get('customer_emotion', '')
                            icon = emotion_icons.get(emotion, "💭")
                            ack_level = miss.get('rep_acknowledgment_level', 'none')
                            
                            st.markdown(f"#### {icon} {emotion.title()} - Timestamp: {miss.get('timestamp', 'N/A')}")
                            
                            if ack_level == 'full':
                                st.success("✅ Rep fully acknowledged this emotion")
                            elif ack_level == 'partial':
                                st.warning("⚠️ Rep partially acknowledged this emotion")
                            else:
                                st.error("❌ Rep did not acknowledge this emotion")
                            
                            # Audio jump button
                            if audio_available and player_id:
                                ts = miss.get('timestamp', '00:00')
                                start_seconds = 0
                                try:
                                    if ':' in ts:
                                        parts = ts.split(':')
                                        if len(parts) == 2:
                                            start_seconds = int(parts[0]) * 60 + int(parts[1])
                                        elif len(parts) == 3:
                                            start_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                                    else:
                                        start_seconds = int(float(ts))
                                except:
                                    start_seconds = 0
                                
                                timestamp_button = f"""
                                    <div style="margin-bottom:15px; padding:10px; background:#f0f8ff; border-radius:5px;">
                                        <button onclick="var p = window.parent.document.getElementById('{player_id}'); if (p) {{ p.currentTime = {start_seconds}; p.play(); window.parent.scrollTo({{top: 0, behavior: 'smooth'}}); }}" 
                                        style="padding:10px 20px; background:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">
                                            ▶ Jump to {ts}
                                        </button>
                                    </div>
                                """
                                components.html(timestamp_button, height=80)
                            
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.markdown("**What Happened:**")
                                st.info(f"**Emotional Signal:** {miss.get('signal', 'N/A')}")
                                
                                rep_attempted = miss.get('rep_attempted', '')
                                if rep_attempted and rep_attempted.lower() not in ['none', '']:
                                    st.warning(f"**Rep Said:** {rep_attempted}")
                                    
                                    what_worked = miss.get('what_worked', '')
                                    if what_worked and what_worked.lower() not in ['none', '']:
                                        st.success(f"**✓ What Worked:** {what_worked}")
                                
                                rep_missed = miss.get('rep_missed_it', '')
                                if rep_missed:
                                    st.error(f"**❌ What Was Missed:** {rep_missed}")
                                
                                why_matters = miss.get('why_it_matters', '')
                                if why_matters:
                                    st.warning(f"**⚠️ Impact:** {why_matters}")
                            
                            with col2:
                                st.markdown("**💡 Complete Empathy Response:**")
                                st.success(f"\"{miss.get('empathy_response', 'N/A')}\"")
                                
                                framework = miss.get('framework_connection', '')
                                if framework:
                                    st.info(f"**🎓 Framework:** {framework}")
                            
                            st.markdown("---")
                    
                    # === OBJECTION HANDLING ===
                    objections = feedback.get('objection_handling_analysis', [])
                    if objections:
                        st.markdown("### 🛡️ Objection Handling Analysis")
                        
                        for obj_idx, obj in enumerate(objections):
                            effectiveness = obj.get('effectiveness_rating', 0)
                            color = "🟢" if effectiveness >= 7 else "🟡" if effectiveness >= 4 else "🔴"
                            
                            st.markdown(f"#### {color} Objection {obj_idx + 1}: \"{obj.get('objection', '')}\"")
                            st.caption(f"Effectiveness: {effectiveness}/10 | Timestamp: {obj.get('timestamp', 'N/A')}")
                            
                            # Audio jump button
                            if audio_available and player_id:
                                ts = obj.get('timestamp', '00:00')
                                start_seconds = 0
                                try:
                                    if ':' in ts:
                                        parts = ts.split(':')
                                        if len(parts) == 2:
                                            start_seconds = int(parts[0]) * 60 + int(parts[1])
                                        elif len(parts) == 3:
                                            start_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                                    else:
                                        start_seconds = int(float(ts))
                                except:
                                    start_seconds = 0
                                
                                timestamp_button = f"""
                                    <div style="margin-bottom:15px; padding:10px; background:#f0f8ff; border-radius:5px;">
                                        <button onclick="var p = window.parent.document.getElementById('{player_id}'); if (p) {{ p.currentTime = {start_seconds}; p.play(); window.parent.scrollTo({{top: 0, behavior: 'smooth'}}); }}" 
                                        style="padding:10px 20px; background:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">
                                            ▶ Jump to {ts}
                                        </button>
                                    </div>
                                """
                                components.html(timestamp_button, height=80)
                            
                            st.markdown("**🎯 The Real Issue:**")
                            st.info(f"{obj.get('real_objection', 'Unknown')}")
                            
                            st.markdown("---")
                            
                            col1, col2 = st.columns([1, 1])
                            
                            with col1:
                                st.markdown("**📋 What Happened:**")
                                st.warning(f"**Rep's Response:** \"{obj.get('rep_response', 'N/A')}\"")
                                
                                rep_attempted = obj.get('rep_attempted', '')
                                if rep_attempted and rep_attempted.lower() not in ['none', '']:
                                    st.info(f"**Rep Attempted:** {rep_attempted}")
                                
                                what_worked = obj.get('what_worked', '')
                                if what_worked and what_worked.lower() not in ['none', 'nothing']:
                                    st.success(f"**✓ What Worked:** {what_worked}")
                            
                            with col2:
                                st.markdown("**❌ Critical Failures:**")
                                failures = obj.get('critical_failures', [])
                                if failures:
                                    for failure in failures:
                                        st.error(f"• {failure}")
                                
                                if obj.get('went_straight_to_discount'):
                                    st.error("💰 **Jumped straight to discount!**")
                                
                                if not obj.get('value_established'):
                                    st.error("⚠️ **Value was NOT established first**")
                            
                            st.markdown("---")
                            
                            st.markdown("**💡 Step-by-Step Better Approach:**")
                            
                            steps = obj.get('step_by_step_better_approach', [])
                            if steps:
                                for step in steps:
                                    step_num = step.get('step', '')
                                    action = step.get('action', '')
                                    example = step.get('example', '')
                                    why = step.get('why', '')
                                    
                                    st.markdown(f"**Step {step_num}: {action}**")
                                    st.success(f"💬 \"{example}\"")
                                    if why:
                                        st.caption(f"📖 {why}")
                                    st.markdown("")
                            
                            st.markdown("**🎓 Framework Recommendation:**")
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                technique = obj.get('sandler_technique_recommended', '')
                                if technique:
                                    st.info(f"**Sandler Technique:** {technique}")
                                
                                why_tech = obj.get('why_this_technique', '')
                                if why_tech:
                                    st.caption(f"💡 {why_tech}")
                            
                            with col2:
                                frameworks = obj.get('framework_connections', '')
                                if frameworks:
                                    st.info(f"**Framework Principles:** {frameworks}")
                            
                            st.markdown("---")
                    
                    # What Went Well / Opportunities
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("### 💚 What Went Well")
                        went_well = feedback.get('what_went_well', [])
                        if went_well:
                            for item in went_well:
                                st.success(f"✓ {item}")
                        else:
                            st.info("Building feedback...")
                    
                    with col2:
                        st.markdown("### 📈 Opportunities to Improve")
                        opportunities = feedback.get('opportunities_to_improve', [])
                        if opportunities:
                            for item in opportunities:
                                st.warning(f"⚠️ {item}")
                        else:
                            st.info("Building feedback...")
                    
                    # Sample Phrases
                    phrases = feedback.get('sample_phrases', {})
                    if phrases:
                        st.markdown("### 💬 Sample Phrases to Practice")
                        
                        phrase_col1, phrase_col2 = st.columns(2)
                        
                        with phrase_col1:
                            if phrases.get('active_listening'):
                                with st.expander("🎧 Active Listening"):
                                    for phrase in phrases.get('active_listening', []):
                                        st.markdown(f"- _{phrase}_")
                            
                            if phrases.get('probing_deeper'):
                                with st.expander("🔍 Probing Deeper"):
                                    for phrase in phrases.get('probing_deeper', []):
                                        st.markdown(f"- _{phrase}_")
                            
                            if phrases.get('emotional_acknowledgment'):
                                with st.expander("💭 Emotional Acknowledgment"):
                                    for phrase in phrases.get('emotional_acknowledgment', []):
                                        st.markdown(f"- _{phrase}_")
                        
                        with phrase_col2:
                            if phrases.get('spin_implication'):
                                with st.expander("🎯 SPIN Implication (Build Value!)"):
                                    for phrase in phrases.get('spin_implication', []):
                                        st.markdown(f"- _{phrase}_")
                            
                            if phrases.get('sandler_pain'):
                                with st.expander("💼 Sandler Pain Questions"):
                                    for phrase in phrases.get('sandler_pain', []):
                                        st.markdown(f"- _{phrase}_")
                    
                    # Show full transcript
                    with st.expander("📄 Full Transcript"):
                        st.text(row['transcript'])

# ===== TAB 2: EXCEPTIONAL MOMENTS =====
with tab2:
    st.header("🌟 Exceptional Moments Feed")
    st.caption("Share these wins with your team!")
    
    exceptional_calls = []
    
    for idx, row in df.iterrows():
        feedback = row['feedback_parsed']
        if feedback:
            exceptional = feedback.get('exceptional_moments', [])
            if exceptional:
                shareworthy = [m for m in exceptional if m.get('shareworthy')]
                if shareworthy:
                    exceptional_calls.append({
                        'idx': idx,
                        'row': row,
                        'moments': shareworthy
                    })
    
    if not exceptional_calls:
        st.info("No exceptional moments found yet. Keep coaching!")
    else:
        for call in exceptional_calls:
            row = call['row']
            with st.expander(f"⭐ {row['agent_name']} - {row['filename']} ({row['date']})"):
                st.write(f"**Agent:** {row['agent_name']}")
                st.write(f"**Call Outcome:** {row['feedback_parsed'].get('call_outcome', 'unknown').upper()}")
                
                st.markdown("---")
                
                for moment in call['moments']:
                    category = moment.get('category', 'general')
                    category_icons = {
                        'objection_handling': '🛡️',
                        'empathy': '❤️',
                        'active_listening': '🎧',
                        'probing': '🔍'
                    }
                    icon = category_icons.get(category, '⭐')
                    
                    st.markdown(f"### {icon} {category.replace('_', ' ').title()}")
                    st.markdown(f"**⏱️ Timestamp: {moment.get('timestamp', 'N/A')}**")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**💬 What Was Said:**")
                        st.info(f"**Customer:** \"{moment.get('customer_quote', 'N/A')}\"")
                        st.success(f"**Rep:** \"{moment.get('rep_quote', 'N/A')}\"")
                    
                    with col2:
                        st.markdown("**🎯 Why This Works:**")
                        st.write(f"**What Happened:** {moment.get('what_happened', 'N/A')}")
                        st.success(f"**Why Exceptional:** {moment.get('why_exceptional', 'N/A')}")
                        if moment.get('coaching_insight'):
                            st.info(f"**Framework:** {moment.get('coaching_insight', '')}")
                    
                    st.markdown("---")

# ===== TAB 3: TEAM ANALYTICS =====
with tab3:
    st.header("📊 Team Analytics Dashboard")
    
    total_calls = len(df)
    
    outcomes = []
    all_scores = []
    
    for _, row in df.iterrows():
        feedback = row['feedback_parsed']
        if feedback:
            outcome = feedback.get('call_outcome', '')
            if outcome:
                outcomes.append(outcome)
            
            scores = feedback.get('call_score', {})
            if scores and isinstance(scores, dict):
                overall = scores.get('overall_score', 0)
                if overall > 0:
                    all_scores.append(overall)
    
    closed = outcomes.count('closed')
    lost = outcomes.count('lost')
    total_outcomes = closed + lost
    close_rate = (closed / total_outcomes * 100) if total_outcomes > 0 else 0
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Calls", total_calls)
    with col2:
        st.metric("Team Close Rate", f"{close_rate:.1f}%")
    with col3:
        st.metric("Avg Score", f"{avg_score:.1f}/10")
    with col4:
        st.metric("Team W/L", f"{closed}/{lost}")
    
    st.markdown("---")
    
    st.subheader("🏆 Agent Leaderboard")
    
    agent_stats = {}
    
    for _, row in df.iterrows():
        agent = row['agent_name']
        if pd.isna(agent):
            continue
            
        if agent not in agent_stats:
            agent_stats[agent] = {
                'calls': 0,
                'closed': 0,
                'lost': 0,
                'scores': []
            }
        
        agent_stats[agent]['calls'] += 1
        
        feedback = row['feedback_parsed']
        if feedback:
            outcome = feedback.get('call_outcome', '')
            if outcome == 'closed':
                agent_stats[agent]['closed'] += 1
            elif outcome == 'lost':
                agent_stats[agent]['lost'] += 1
            
            scores = feedback.get('call_score', {})
            if scores and isinstance(scores, dict):
                overall = scores.get('overall_score', 0)
                if overall > 0:
                    agent_stats[agent]['scores'].append(overall)
    
    leaderboard = []
    for agent, stats in agent_stats.items():
        total = stats['closed'] + stats['lost']
        close_rate = (stats['closed'] / total * 100) if total > 0 else 0
        avg_score = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0
        
        leaderboard.append({
            'Agent': agent,
            'Calls': stats['calls'],
            'Close Rate': f"{close_rate:.1f}%",
            'Avg Score': f"{avg_score:.1f}/10",
            'Closed': stats['closed'],
            'Lost': stats['lost']
        })
    
    if leaderboard:
        leaderboard_df = pd.DataFrame(leaderboard)
        leaderboard_df = leaderboard_df.sort_values('Close Rate', ascending=False)
        st.dataframe(leaderboard_df, use_container_width=True, hide_index=True)
    else:
        st.info("Not enough data yet")

# ===== TAB 4: CALL SEARCH =====
with tab4:
    st.header("🔍 Advanced Call Search")
    
    search_type = st.selectbox(
        "Search By:",
        ["Keyword", "Customer Intent", "Objection Type", "Service Type", "Outcome"]
    )
    
    if search_type == "Keyword":
        keyword = st.text_input("Search transcripts for:")
        if keyword:
            matches = []
            for idx, row in df.iterrows():
                if keyword.lower() in str(row['transcript']).lower():
                    matches.append(row)
            
            st.write(f"Found **{len(matches)}** calls mentioning '{keyword}'")
            
            for row in matches:
                with st.expander(f"📞 {row['agent_name']} - {row['filename']}"):
                    feedback = row['feedback_parsed']
                    if feedback:
                        st.write(f"**Summary:** {feedback.get('summary', '')}")
                    st.write(f"**Transcript excerpt:** {str(row['transcript'])[:300]}...")

st.sidebar.markdown("---")
st.sidebar.caption("🎓 Powered by SPIN + Sandler")

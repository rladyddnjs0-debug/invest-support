import streamlit as st
import os
from datetime import datetime

st.set_page_config(page_title="Admin System Logs", layout="wide")

st.title("📋 시스템 로그 관리자")

# 로그 디렉토리 설정
log_dir = "logs"
log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".log")], reverse=True) if os.path.exists(log_dir) else []

if not log_files:
    st.info("기록된 로그 파일이 없습니다.")
    if st.button("홈으로 돌아가기"):
        st.switch_page("app.py")
    st.stop()

# 파일 선택 및 검색 인터페이스
col1, col2 = st.columns([1, 1])
with col1:
    selected_log = st.selectbox("로그 파일 선택", log_files)
with col2:
    search_query = st.text_input("🔍 로그 검색 (키워드)", "")

log_path = os.path.join(log_dir, selected_log)

if os.path.exists(log_path):
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        # 검색 필터링
        if search_query:
            filtered_lines = [line for line in lines if search_query.lower() in line.lower()]
            st.caption(f"검색 결과: {len(filtered_lines)}개 / 전체 {len(lines)}개")
        else:
            filtered_lines = lines
            
        # 최신 로그가 위에 오도록 정렬 옵션
        sort_order = st.radio("정렬 순서", ["최신순", "과거순"], horizontal=True)
        if sort_order == "최신순":
            display_lines = filtered_lines[::-1]
        else:
            display_lines = filtered_lines

        # 로그 출력
        if not display_lines:
            st.warning("조건에 맞는 로그가 없습니다.")
        else:
            # 대용량 로그 처리를 위해 슬라이싱 (최근 500줄 제한)
            max_display = 500
            display_text = "".join(display_lines[:max_display])
            if len(display_lines) > max_display:
                st.info(f"표시 제한: 상위 {max_display}줄만 표시됩니다.")
            
            st.code(display_text, language="log")

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🔄 로그 새로고침"):
                st.rerun()
        with c2:
            if st.button("🗑️ 현재 로그 파일 삭제", type="secondary"):
                os.remove(log_path)
                st.success(f"{selected_log} 파일이 삭제되었습니다.")
                st.rerun()
        with c3:
            if st.button("🏠 홈으로 돌아가기"):
                st.switch_page("app.py")

    except Exception as e:
        st.error(f"로그를 읽는 중 오류가 발생했습니다: {e}")
else:
    st.error("선택한 로그 파일을 찾을 수 없습니다.")

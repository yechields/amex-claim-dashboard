import streamlit as st
import pandas as pd
from datetime import date
from pathlib import Path
import storage
from storage import upsert_purchase, update_purchase, fetch_audit
from importers import import_amex_csv, parse_receipt_file
from rules import evaluate
from packet import generate_packet
from config import ANNUAL_LIMIT

st.set_page_config(page_title='Amex Return Protection Dashboard', layout='wide')

con = storage.connect()

st.title('Amex Return Protection Dashboard')
st.caption('Local-first claim assistant. It prepares and organizes claims; you approve and submit.')

with st.sidebar:
    st.header('Import')
    amex_file = st.file_uploader('Upload Amex transaction CSV', type=['csv'], key='amex')
    if amex_file and st.button('Import Amex CSV'):
        records, err = import_amex_csv(amex_file)
        if err:
            st.error(err)
        created = 0
        for rec in records:
            _, is_new = upsert_purchase(con, rec)
            created += int(is_new)
        st.success(f'Imported {len(records)} rows, {created} new purchases.')
        st.rerun()

    receipt_files = st.file_uploader('Upload receipt/order files', type=['eml','html','htm','txt','csv'], accept_multiple_files=True)
    if receipt_files and st.button('Import receipts'):
        total = 0
        warnings = []
        for f in receipt_files:
            records, err = parse_receipt_file(f)
            if err:
                warnings.append(f'{f.name}: {err}')
            for rec in records:
                upsert_purchase(con, rec)
                total += 1
        st.success(f'Imported {total} receipt-derived purchases.')
        for w in warnings:
            st.warning(w)
        st.rerun()

rows = [dict(r) for r in storage.fetch_purchases(con)]
for r in rows:
    r.update(evaluate(r))

df = pd.DataFrame(rows)

if df.empty:
    st.info('Import an Amex CSV or receipt files to begin. Sample CSV is included in sample_exports/sample_amex.csv.')
else:
    candidates = df[df['candidate'] == True]
    urgent = df[df['urgent'] == True]
    submitted_total = df[df['status'].eq('submitted')].assign(year=lambda x: pd.to_datetime(x['purchase_date']).dt.year)
    this_year_total = submitted_total[submitted_total['year'].eq(date.today().year)]['amount'].sum() if not submitted_total.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Tracked purchases', len(df))
    c2.metric('Claim candidates', len(candidates))
    c3.metric('Urgent', len(urgent))
    c4.metric('Submitted cap used', f'${this_year_total:,.0f} / ${ANNUAL_LIMIT:,.0f}')

    tab1, tab2, tab3, tab4 = st.tabs(['Action Queue', 'All Purchases', 'Claim Packets', 'Audit Log'])

    with tab1:
        st.subheader('Action Queue')
        if candidates.empty:
            st.success('No current claim candidates.')
        else:
            for _, row in candidates.sort_values(['urgent','days_left','amount'], ascending=[False, True, False]).iterrows():
                with st.expander(f"{'URGENT - ' if row['urgent'] else ''}{row['merchant']} | ${row['amount']:.2f} | {row['days_left']} days left", expanded=row['urgent']):
                    st.write(f"**Purchase date:** {row['purchase_date']}  ")
                    st.write(f"**Description:** {row.get('description') or ''}")
                    if row['blocked_reasons']:
                        st.warning('Review: ' + '; '.join(row['blocked_reasons']))
                    if row['needs_docs']:
                        st.info('Needs: ' + ', '.join(row['needs_docs']))
                    col_a, col_b, col_c, col_d = st.columns(4)
                    with col_a:
                        unused = st.checkbox('Unused/new', value=bool(row['item_unused']), key=f'unused_{row.id}')
                    with col_b:
                        refused = st.checkbox('Merchant refused/expired', value=bool(row['merchant_refused']), key=f'refused_{row.id}')
                    with col_c:
                        approved = st.checkbox('Approve claim prep', value=bool(row['user_approved']), key=f'appr_{row.id}')
                    with col_d:
                        if st.button('Save', key=f'save_{row.id}'):
                            update_purchase(con, int(row['id']), item_unused=int(unused), merchant_refused=int(refused), user_approved=int(approved))
                            st.rerun()
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button('Generate claim packet', key=f'packet_{row.id}'):
                            latest = dict(con.execute('SELECT * FROM purchases WHERE id=?', (int(row['id']),)).fetchone())
                            latest.update(evaluate(latest))
                            folder = generate_packet(latest)
                            st.success(f'Packet created: {folder}')
                    with col2:
                        if st.button('Mark submitted', key=f'sub_{row.id}'):
                            update_purchase(con, int(row['id']), status='submitted')
                            st.rerun()
                    with col3:
                        if st.button('Ignore', key=f'ign_{row.id}'):
                            update_purchase(con, int(row['id']), status='ignored')
                            st.rerun()

    with tab2:
        st.subheader('All Purchases')
        show_cols = ['id','purchase_date','merchant','description','amount','card','status','age_days','claim_deadline','days_left','candidate','urgent']
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)
        st.divider()
        st.subheader('Edit selected purchase')
        selected = st.selectbox('Purchase ID', df['id'].tolist())
        row = df[df['id'].eq(selected)].iloc[0].to_dict()
        new_status = st.selectbox('Status', ['monitoring','ignored','submitted','closed'], index=['monitoring','ignored','submitted','closed'].index(row.get('status','monitoring')))
        notes = st.text_area('Notes', value=row.get('notes') or '')
        if st.button('Update selected purchase'):
            update_purchase(con, int(selected), status=new_status, notes=notes)
            st.rerun()

    with tab3:
        st.subheader('Generated Packet Folders')
        base = Path('claim_packets')
        folders = [p for p in base.glob('*') if p.is_dir()]
        if not folders:
            st.info('No packets generated yet.')
        else:
            for p in sorted(folders, reverse=True):
                st.write(f'**{p.name}**')
                for f in p.iterdir():
                    st.write(f'- {f.name}')

    with tab4:
        st.subheader('Audit Log')
        audit = [dict(x) for x in fetch_audit(con)]
        st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)

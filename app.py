import html
import re
import uuid
from datetime import date, timedelta
import gspread
import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials

# ==========================================
# KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="Catatan Keuangan & Aset Pro",
    page_icon="💰",
    layout="wide",
)


# ==========================================
# SISTEM LOGIN MULTI-USER
# ==========================================
def cek_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""

    if not st.session_state.logged_in:
        col_kiri, col_tengah, col_kanan = st.columns([1, 1.2, 1])
        with col_tengah:
            st.title("🔐 Login Keuangan Pro")
            st.caption("Masukkan username dan password akun pribadi.")

            with st.form("form_login"):
                username = st.text_input("Username", placeholder="Contoh: rina").strip().lower()
                password = st.text_input("Password", type="password")
                masuk = st.form_submit_button("Masuk", type="primary", use_container_width=True)

                if masuk:
                    users = st.secrets.get("USERS", {})
                    users_lower = {k.strip().lower(): str(v) for k, v in users.items()}

                    if username in users_lower and password == users_lower[username]:
                        st.session_state.logged_in = True
                        st.session_state.username = username
                        st.rerun()
                    else:
                        st.error("Username atau password salah.")
        st.stop()


cek_login()
CURRENT_USER = st.session_state.username


# ==========================================
# KONEKSI GOOGLE SHEETS
# ==========================================
@st.cache_resource
def init_gsheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_url(st.secrets["SHEET_URL"])


try:
    sh = init_gsheet()
except Exception as e:
    st.error(
        f"Gagal terhubung ke Google Sheets. Pastikan `SHEET_URL` dan `gcp_service_account` "
        f"di `.streamlit/secrets.toml` sudah benar.\n\nDetail: {e}"
    )
    st.stop()


def get_or_create_worksheet(nama_tab: str, kolom: list) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(nama_tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=nama_tab, rows=2000, cols=len(kolom))
        ws.append_row(kolom)
    return ws


def load_all_df(nama_tab: str, kolom: list) -> pd.DataFrame:
    ws = get_or_create_worksheet(nama_tab, kolom)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=kolom)
    df = pd.DataFrame(data)
    for k in kolom:
        if k not in df.columns:
            df[k] = ""
    return df[kolom]


def load_user_df(nama_tab: str, kolom: list, username: str) -> pd.DataFrame:
    df_all = load_all_df(nama_tab, kolom)
    if df_all.empty:
        return pd.DataFrame(columns=kolom)
    df_all["username"] = df_all["username"].astype(str).str.strip().str.lower()
    return df_all[df_all["username"] == username].copy().reset_index(drop=True)


def save_user_df(nama_tab: str, df_user: pd.DataFrame, kolom: list, username: str) -> None:
    """Menyimpan data user aktif tanpa mengganggu data milik user lain."""
    ws = get_or_create_worksheet(nama_tab, kolom)
    df_all = load_all_df(nama_tab, kolom)

    if not df_all.empty:
        df_all["username"] = df_all["username"].astype(str).str.strip().str.lower()
        df_others = df_all[df_all["username"] != username].copy()
    else:
        df_others = pd.DataFrame(columns=kolom)

    df_user_save = df_user.copy()
    df_user_save["username"] = username
    for k in kolom:
        if k not in df_user_save.columns:
            df_user_save[k] = ""

    df_merged = pd.concat([df_others[kolom], df_user_save[kolom]], ignore_index=True)
    for col in df_merged.columns:
        df_merged[col] = df_merged[col].astype(str)

    ws.clear()
    ws.update([kolom] + df_merged[kolom].values.tolist())


# ==========================================
# KONSTANTA KOLOM & KATEGORI
# ==========================================
KOLOM_ASET = ["username", "id", "jenis_saldo", "nama_akun", "berat_gram", "saldo_awal", "keterangan"]
KOLOM_TRANSAKSI = ["username", "id", "tanggal", "jenis", "akun_saldo", "kategori", "nominal", "keterangan"]
KOLOM_HUTANG = [
    "username",
    "id",
    "tanggal",
    "asal_hutang",
    "jenis_hutang",
    "nama_hutang",
    "pemberi_pinjaman",
    "total_hutang",
    "sudah_dibayar",
    "status",
    "keterangan",
]
KOLOM_PENGATURAN = ["username", "key", "value"]

JENIS_SALDO = [
    "Tabungan",
    "Kas Tunai",
    "Emas",
    "SBN",
    "Saham",
    "RDPU",
    "Deposito",
    "E-Wallet",
    "Lainnya",
]

JENIS_HUTANG = [
    "Cicilan KPR",
    "Hutang Koperasi",
    "Hutang Bank",
    "Hutang Emas",
    "Kartu Kredit",
    "Pinjaman Pribadi",
    "Lainnya",
]

KATEGORI_PENDAPATAN = [
    "Gaji",
    "Tunjangan / Sertifikasi",
    "Bonus",
    "Hasil Usaha",
    "Kupon SBN / Dividen / Imbal Hasil",
    "Lainnya",
]

KATEGORI_PENGELUARAN = [
    "Rutin (Tagihan / Bulanan)",
    "Konsumsi & Belanja Harian",
    "Simpanan / Investasi",
    "Kecantikan & Perawatan",
    "Transportasi",
    "Cicilan / Bayar Hutang",
    "Hiburan & Gaya Hidup",
    "Kesehatan",
    "Sosial / Sedekah",
    "Lainnya",
]


# ==========================================
# FUNGSI BANTUAN FORMAT, INPUT & PRINT
# ==========================================
def format_rp(angka: float) -> str:
    return f"Rp {angka:,.0f}".replace(",", ".")


def parse_nominal(teks: str) -> float:
    bersih = re.sub(r"[^\d]", "", str(teks))
    return float(bersih) if bersih else 0.0


def input_nominal(
    label: str,
    value: float = 0.0,
    key: str | None = None,
    help: str | None = None,
    placeholder: str = "Contoh: 1,500,000",
) -> float:
    default_str = f"{value:,.0f}" if value > 0 else ""
    teks = st.text_input(
        label,
        value=default_str,
        placeholder=placeholder,
        key=key,
        help=help,
    )
    return parse_nominal(teks)


def buat_tombol_print(df_cetak: pd.DataFrame, username: str, tgl_mulai: date, tgl_selesai: date):
    """Membuat tombol Print yang membuka jendela cetak bersih (khusus tabel & ringkasan)."""
    tot_masuk = df_cetak[df_cetak["jenis"] == "Pendapatan"]["nominal"].sum()
    tot_keluar = df_cetak[df_cetak["jenis"] == "Pengeluaran"]["nominal"].sum()
    selisih = tot_masuk - tot_keluar

    baris_html = ""
    for _, r in df_cetak.iterrows():
        baris_html += (
            "<tr>"
            f"<td>{html.escape(str(r['tanggal']))}</td>"
            f"<td>{html.escape(str(r['jenis']))}</td>"
            f"<td>{html.escape(str(r['akun_saldo']))}</td>"
            f"<td>{html.escape(str(r['kategori']))}</td>"
            f"<td style='text-align:right;'>{html.escape(format_rp(r['nominal']))}</td>"
            f"<td>{html.escape(str(r['keterangan']))}</td>"
            "</tr>"
        )

    dokumen_html = f"""
    <html>
    <head>
        <title>Laporan Transaksi - {html.escape(username.capitalize())}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 24px; color: #222; }}
            h2 {{ margin-bottom: 4px; }}
            .meta {{ color: #555; font-size: 13px; margin-bottom: 16px; }}
            .ringkasan {{ display: flex; gap: 16px; margin-bottom: 18px; }}
            .box {{ border: 1px solid #ccc; border-radius: 6px; padding: 10px 14px; flex: 1; }}
            .box small {{ color: #666; display: block; margin-bottom: 4px; }}
            .box strong {{ font-size: 15px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
            th, td {{ border: 1px solid #ccc; padding: 7px 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h2>Laporan Transaksi Keuangan — {html.escape(username.capitalize())}</h2>
        <div class="meta">Periode: {tgl_mulai.strftime('%d/%m/%Y')} s.d. {tgl_selesai.strftime('%d/%m/%Y')} | Dicetak: {date.today().strftime('%d/%m/%Y')}</div>
        <div class="ringkasan">
            <div class="box"><small>Total Pendapatan</small><strong>{format_rp(tot_masuk)}</strong></div>
            <div class="box"><small>Total Pengeluaran</small><strong>{format_rp(tot_keluar)}</strong></div>
            <div class="box"><small>Selisih (Masuk - Keluar)</small><strong>{format_rp(selisih)}</strong></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Tanggal</th>
                    <th>Jenis</th>
                    <th>Akun</th>
                    <th>Kategori</th>
                    <th style="text-align:right;">Nominal</th>
                    <th>Keterangan</th>
                </tr>
            </thead>
            <tbody>{baris_html}</tbody>
        </table>
    </body>
    </html>
    """

    dokumen_js = dokumen_html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    components.html(
        f"""
        <button onclick="cetakLaporan()" style="
            background-color: #ff4b4b;
            color: white;
            border: none;
            padding: 9px 18px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
        ">🖨️ Print / Simpan PDF Laporan</button>
        <script>
            function cetakLaporan() {{
                var w = window.open('', '_blank', 'width=950,height=700');
                w.document.open();
                w.document.write(`{dokumen_js}`);
                w.document.close();
                w.focus();
                setTimeout(function() {{ w.print(); }}, 300);
            }}
        </script>
        """,
        height=48,
    )


# ==========================================
# MUAT DATA KHUSUS USER AKTIF
# ==========================================
df_pengaturan = load_user_df("pengaturan", KOLOM_PENGATURAN, CURRENT_USER)
harga_emas = 1500000.0
if not df_pengaturan.empty:
    row_emas = df_pengaturan[df_pengaturan["key"] == "harga_emas_per_gram"]
    if not row_emas.empty:
        try:
            harga_emas = float(row_emas.iloc[0]["value"])
        except ValueError:
            harga_emas = 1500000.0

df_aset = load_user_df("aset", KOLOM_ASET, CURRENT_USER)
df_transaksi = load_user_df("transaksi", KOLOM_TRANSAKSI, CURRENT_USER)
df_hutang = load_user_df("hutang", KOLOM_HUTANG, CURRENT_USER)

if not df_aset.empty:
    df_aset["berat_gram"] = pd.to_numeric(df_aset["berat_gram"], errors="coerce").fillna(0.0)
    df_aset["saldo_awal"] = pd.to_numeric(df_aset["saldo_awal"], errors="coerce").fillna(0.0)

if not df_transaksi.empty:
    df_transaksi["nominal"] = pd.to_numeric(df_transaksi["nominal"], errors="coerce").fillna(0.0)
    df_transaksi["tanggal"] = pd.to_datetime(df_transaksi["tanggal"], errors="coerce").dt.date

if not df_hutang.empty:
    df_hutang["total_hutang"] = pd.to_numeric(df_hutang["total_hutang"], errors="coerce").fillna(0.0)
    df_hutang["sudah_dibayar"] = pd.to_numeric(df_hutang["sudah_dibayar"], errors="coerce").fillna(0.0)
    df_hutang["tanggal"] = pd.to_datetime(df_hutang["tanggal"], errors="coerce").dt.date


# ==========================================
# SIDEBAR: INFO USER & PENGATURAN HARGA EMAS
# ==========================================
with st.sidebar:
    st.title("💰 Keuangan Pro")
    st.success(f"👤 Akun aktif: **{CURRENT_USER}**")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()

    st.divider()
    st.markdown("### 🪙 Harga Emas per Gram")
    st.caption("Semua aset berjenis **Emas** milik akun ini otomatis dikonversi ke Rupiah.")

    with st.form("form_harga_emas"):
        input_harga_emas = input_nominal(
            "Harga Emas / Buyback (Rp/gram)",
            value=float(harga_emas),
            key="input_harga_emas_rp",
            placeholder="Contoh: 2,270,000",
        )
        if st.form_submit_button("Update Harga Emas", type="primary", use_container_width=True):
            if input_harga_emas <= 0:
                st.warning("Harga emas harus lebih dari 0.")
            else:
                df_set_baru = pd.DataFrame(
                    [{"username": CURRENT_USER, "key": "harga_emas_per_gram", "value": input_harga_emas}]
                )
                save_user_df("pengaturan", df_set_baru, KOLOM_PENGATURAN, CURRENT_USER)
                st.success(f"Harga emas diperbarui ke {format_rp(input_harga_emas)}/gram!")
                st.rerun()


# ==========================================
# HITUNG RINGKASAN KEUANGAN USER AKTIF
# ==========================================
if not df_aset.empty:
    saldo_awal_efektif_list = []
    saldo_saat_ini_list = []
    for _, row in df_aset.iterrows():
        nama = row["nama_akun"]
        if row["jenis_saldo"] == "Emas" and row["berat_gram"] > 0:
            awal = row["berat_gram"] * harga_emas
        else:
            awal = row["saldo_awal"]

        if df_transaksi.empty:
            masuk = 0.0
            keluar = 0.0
        else:
            masuk = df_transaksi[
                (df_transaksi["akun_saldo"] == nama)
                & (df_transaksi["jenis"].isin(["Pendapatan", "Transfer Masuk"]))
            ]["nominal"].sum()
            keluar = df_transaksi[
                (df_transaksi["akun_saldo"] == nama)
                & (df_transaksi["jenis"].isin(["Pengeluaran", "Transfer Keluar"]))
            ]["nominal"].sum()

        saldo_awal_efektif_list.append(awal)
        saldo_saat_ini_list.append(awal + masuk - keluar)

    df_aset["saldo_awal_rp"] = saldo_awal_efektif_list
    df_aset["saldo_saat_ini"] = saldo_saat_ini_list
else:
    df_aset["saldo_awal_rp"] = pd.Series(dtype="float")
    df_aset["saldo_saat_ini"] = pd.Series(dtype="float")

total_saldo_awal = df_aset["saldo_awal_rp"].sum() if not df_aset.empty else 0.0
total_pendapatan = (
    df_transaksi[df_transaksi["jenis"] == "Pendapatan"]["nominal"].sum()
    if not df_transaksi.empty
    else 0.0
)
total_pengeluaran = (
    df_transaksi[df_transaksi["jenis"] == "Pengeluaran"]["nominal"].sum()
    if not df_transaksi.empty
    else 0.0
)
total_saldo_akhir = df_aset["saldo_saat_ini"].sum() if not df_aset.empty else 0.0
total_sisa_hutang = (
    (df_hutang["total_hutang"] - df_hutang["sudah_dibayar"]).clip(lower=0).sum()
    if not df_hutang.empty
    else 0.0
)
kekayaan_bersih = total_saldo_akhir - total_sisa_hutang


# ==========================================
# HEADER & METRIK UTAMA
# ==========================================
st.title(f"💰 Dashboard Keuangan — {CURRENT_USER.capitalize()}")

r1c1, r1c2, r1c3 = st.columns(3)
r1c1.metric("🏦 Total Saldo Awal (Semua Aset)", format_rp(total_saldo_awal))
r1c2.metric("📈 Total Pendapatan", format_rp(total_pendapatan))
r1c3.metric("📉 Total Pengeluaran", format_rp(total_pengeluaran))

r2c1, r2c2, r2c3 = st.columns(3)
r2c1.metric("💵 Total Saldo & Aset Saat Ini", format_rp(total_saldo_akhir))
r2c2.metric("🧾 Total Sisa Hutang", format_rp(total_sisa_hutang))
r2c3.metric("💎 Kekayaan Bersih (Aset - Hutang)", format_rp(kekayaan_bersih))

st.divider()


# ==========================================
# TAB NAVIGASI UTAMA
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "🏦 Saldo & Aset",
        "➕ Catat Transaksi",
        "🧾 Manajemen Hutang",
        "📊 Grafik & Analisis",
        "📋 Riwayat, Print & Hapus",
    ]
)

# --- TAB 1: SALDO & ASET MULTI-JENIS ---
with tab1:
    c_a1, c_a2 = st.columns([1, 1.6])

    with c_a1:
        st.subheader("Tambah Pos Saldo / Aset Awal")
        st.caption("Dicatat terpisah di luar pendapatan dan hutang.")

        jenis_saldo = st.selectbox(
            "Jenis Saldo / Aset",
            JENIS_SALDO,
            key="pilih_jenis_saldo",
        )

        with st.form(f"form_tambah_aset_{jenis_saldo}", clear_on_submit=True):
            nama_akun = st.text_input(
                "Nama Akun / Instrumen",
                placeholder="Contoh: Emas Galeri 24 / Tabungan BCA / SBN / RDPU",
                key=f"nama_akun_{jenis_saldo}",
            )

            if jenis_saldo == "Emas":
                berat_gram = st.number_input(
                    "Berat Emas (gram)",
                    min_value=0.0,
                    step=0.5,
                    format="%.2f",
                    key="input_berat_gram_emas",
                )
                st.info(
                    f"🪙 Acuan harga saat ini: **{format_rp(harga_emas)}/gram** "
                    f"(otomatis dikalikan saat disimpan)."
                )
                nominal_awal = 0.0
            else:
                berat_gram = 0.0
                nominal_awal = input_nominal(
                    "Nominal Saldo Awal (Rp)",
                    value=0.0,
                    key="input_nominal_saldo_rp",
                    placeholder="Contoh: 15,000,000",
                )

            ket_aset = st.text_input(
                "Keterangan",
                placeholder="Opsional",
                key=f"ket_aset_{jenis_saldo}",
            )

            if st.form_submit_button("Simpan Pos Saldo", type="primary", use_container_width=True):
                if not nama_akun.strip():
                    st.warning("Nama akun tidak boleh kosong!")
                elif not df_aset.empty and nama_akun.strip() in df_aset["nama_akun"].values:
                    st.warning("Nama akun sudah ada. Gunakan nama yang berbeda.")
                elif jenis_saldo == "Emas" and berat_gram <= 0:
                    st.warning("Masukkan berat emas lebih dari 0 gram.")
                else:
                    aset_baru = pd.DataFrame(
                        [
                            {
                                "username": CURRENT_USER,
                                "id": str(uuid.uuid4())[:8],
                                "jenis_saldo": jenis_saldo,
                                "nama_akun": nama_akun.strip(),
                                "berat_gram": berat_gram,
                                "saldo_awal": nominal_awal if jenis_saldo != "Emas" else berat_gram * harga_emas,
                                "keterangan": ket_aset if ket_aset else "-",
                            }
                        ]
                    )
                    df_aset_save = pd.concat(
                        [df_aset.drop(columns=["saldo_awal_rp", "saldo_saat_ini"], errors="ignore"), aset_baru],
                        ignore_index=True,
                    )
                    save_user_df("aset", df_aset_save, KOLOM_ASET, CURRENT_USER)
                    st.success(f"Pos **{nama_akun}** ({jenis_saldo}) tersimpan ke Google Sheets!")
                    st.rerun()

    with c_a2:
        st.subheader("Daftar Saldo & Aset Saat Ini")
        if df_aset.empty:
            st.info("Belum ada pos saldo. Silakan tambahkan dulu di sebelah kiri.")
        else:
            tampil_aset = df_aset.copy()
            tampil_aset["gram"] = tampil_aset.apply(
                lambda r: f"{r['berat_gram']:.2f} gr" if r["jenis_saldo"] == "Emas" else "-",
                axis=1,
            )
            tampil_aset["nilai_rupiah"] = tampil_aset["saldo_saat_ini"].map(format_rp)

            st.dataframe(
                tampil_aset[["jenis_saldo", "nama_akun", "gram", "nilai_rupiah", "keterangan"]].rename(
                    columns={
                        "jenis_saldo": "Jenis Saldo",
                        "nama_akun": "Nama Akun",
                        "gram": "Gram",
                        "nilai_rupiah": "Nilai Saat Ini",
                        "keterangan": "Keterangan",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("#### Ringkasan per Jenis Saldo")
            ringkasan_aset = (
                df_aset.groupby("jenis_saldo", as_index=False)["saldo_saat_ini"]
                .sum()
                .sort_values(by="saldo_saat_ini", ascending=False)
            )
            ringkasan_aset["saldo_saat_ini"] = ringkasan_aset["saldo_saat_ini"].map(format_rp)
            st.dataframe(
                ringkasan_aset.rename(
                    columns={"jenis_saldo": "Jenis Saldo", "saldo_saat_ini": "Total Nilai"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            with st.expander("Hapus Pos Saldo"):
                hapus_akun = st.selectbox("Pilih akun yang ingin dihapus", df_aset["nama_akun"].tolist())
                if st.button("Hapus Akun Terpilih"):
                    df_aset_save = df_aset[df_aset["nama_akun"] != hapus_akun].drop(
                        columns=["saldo_awal_rp", "saldo_saat_ini"], errors="ignore"
                    )
                    save_user_df("aset", df_aset_save, KOLOM_ASET, CURRENT_USER)
                    st.success(f"Akun `{hapus_akun}` dihapus.")
                    st.rerun()

# --- TAB 2: CATAT TRANSAKSI & PINDAH SALDO / TOP-UP ---
with tab2:
    st.subheader("Input Transaksi / Pindah Saldo")
    daftar_akun = df_aset["nama_akun"].tolist() if not df_aset.empty else []

    mode_trx = st.radio(
        "Pilih Jenis Pencatatan",
        ["Pengeluaran", "Pendapatan", "🔄 Pindah Saldo / Top-Up"],
        horizontal=True,
        key="mode_trx_radio",
    )

    if mode_trx in ["Pengeluaran", "Pendapatan"]:
        daftar_kategori = KATEGORI_PENDAPATAN if mode_trx == "Pendapatan" else KATEGORI_PENGELUARAN
        opsi_akun = daftar_akun if daftar_akun else ["Umum (Belum Ada Pos Saldo)"]

        with st.form(f"form_transaksi_{mode_trx}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                tgl_trx = st.date_input("Tanggal", value=date.today())
                akun_trx = st.selectbox(
                    "Masuk ke Akun" if mode_trx == "Pendapatan" else "Keluar dari Akun",
                    opsi_akun,
                )
                kategori_trx = st.selectbox("Kategori", daftar_kategori)
            with c2:
                nominal_trx = input_nominal(
                    "Nominal (Rp)",
                    value=0.0,
                    key=f"input_nominal_trx_{mode_trx}",
                    placeholder="Contoh: 250,000",
                )
                ket_trx = st.text_input("Keterangan", placeholder="Contoh: Gaji / Beli skincare / Rutin")

            if st.form_submit_button(f"Simpan {mode_trx}", type="primary", use_container_width=True):
                if nominal_trx <= 0:
                    st.warning("Nominal harus lebih dari 0!")
                else:
                    baru = pd.DataFrame(
                        [
                            {
                                "username": CURRENT_USER,
                                "id": str(uuid.uuid4())[:8],
                                "tanggal": str(tgl_trx),
                                "jenis": mode_trx,
                                "akun_saldo": akun_trx,
                                "kategori": kategori_trx,
                                "nominal": nominal_trx,
                                "keterangan": ket_trx if ket_trx else "-",
                            }
                        ]
                    )
                    df_transaksi = pd.concat([df_transaksi, baru], ignore_index=True)
                    save_user_df("transaksi", df_transaksi, KOLOM_TRANSAKSI, CURRENT_USER)
                    st.success(
                        f"{mode_trx} **{kategori_trx}** ({akun_trx}) sebesar {format_rp(nominal_trx)} tersimpan!"
                    )
                    st.rerun()

    else:
        st.caption(
            "Memindahkan dana antar akun (misal: dari Tabungan ke RDPU, SBN, Emas, atau E-Wallet) "
            "tanpa menambah angka Pendapatan atau Pengeluaran."
        )
        if len(daftar_akun) < 2:
            st.warning("Tambahkan minimal 2 akun di tab **🏦 Saldo & Aset** dulu supaya bisa pindah saldo.")
        else:
            with st.form("form_pindah_saldo", clear_on_submit=True):
                t1, t2 = st.columns(2)
                with t1:
                    tgl_tf = st.date_input("Tanggal Pindah / Top-Up", value=date.today())
                    akun_asal = st.selectbox("Dari Akun (Sumber Dana)", daftar_akun, index=0)
                    akun_tujuan = st.selectbox("Ke Akun (Tujuan Top-Up)", daftar_akun, index=1)
                with t2:
                    nominal_tf = input_nominal(
                        "Nominal (Rp)",
                        value=0.0,
                        key="input_nominal_tf",
                        placeholder="Contoh: 2,000,000",
                    )
                    ket_tf = st.text_input(
                        "Keterangan", placeholder="Contoh: Top-up RDPU / Beli Emas / Pindah ke E-Wallet"
                    )

                if st.form_submit_button("Simpan Pindah Saldo", type="primary", use_container_width=True):
                    if nominal_tf <= 0:
                        st.warning("Nominal harus lebih dari 0.")
                    elif akun_asal == akun_tujuan:
                        st.warning("Akun asal dan akun tujuan tidak boleh sama.")
                    else:
                        trx_tf = pd.DataFrame(
                            [
                                {
                                    "username": CURRENT_USER,
                                    "id": str(uuid.uuid4())[:8],
                                    "tanggal": str(tgl_tf),
                                    "jenis": "Transfer Keluar",
                                    "akun_saldo": akun_asal,
                                    "kategori": "Pindah Saldo / Top-Up",
                                    "nominal": nominal_tf,
                                    "keterangan": f"Ke {akun_tujuan}" + (f" ({ket_tf})" if ket_tf else ""),
                                },
                                {
                                    "username": CURRENT_USER,
                                    "id": str(uuid.uuid4())[:8],
                                    "tanggal": str(tgl_tf),
                                    "jenis": "Transfer Masuk",
                                    "akun_saldo": akun_tujuan,
                                    "kategori": "Pindah Saldo / Top-Up",
                                    "nominal": nominal_tf,
                                    "keterangan": f"Dari {akun_asal}" + (f" ({ket_tf})" if ket_tf else ""),
                                },
                            ]
                        )
                        df_transaksi = pd.concat([df_transaksi, trx_tf], ignore_index=True)
                        save_user_df("transaksi", df_transaksi, KOLOM_TRANSAKSI, CURRENT_USER)
                        st.success(
                            f"Berhasil memindahkan {format_rp(nominal_tf)} dari **{akun_asal}** ke **{akun_tujuan}**!"
                        )
                        st.rerun()

# --- TAB 3: MANAJEMEN HUTANG MULTI-JENIS ---
with tab3:
    col_h1, col_h2 = st.columns(2)

    with col_h1:
        st.subheader("Tambah Catatan Hutang (Awal / Baru)")
        with st.form("form_hutang_baru", clear_on_submit=True):
            asal_hutang = st.radio(
                "Asal Hutang",
                ["Hutang Awal (Sudah Ada)", "Hutang Baru"],
                horizontal=True,
            )
            jenis_hutang = st.selectbox("Jenis Hutang", JENIS_HUTANG)
            tgl_hutang = st.date_input("Tanggal Pencatatan", value=date.today())
            nama_hutang = st.text_input(
                "Nama Hutang", placeholder="Contoh: KPR Apartemen / Koperasi / Bank"
            )
            pemberi = st.text_input("Pemberi Pinjaman / Lembaga", placeholder="Contoh: Bank Mandiri / Koperasi")
            nominal_hutang = input_nominal(
                "Total Hutang (Rp)",
                value=0.0,
                key="input_nominal_hutang",
                placeholder="Contoh: 50,000,000",
            )
            ket_hutang = st.text_input("Keterangan Tambahan", placeholder="Opsional")

            if st.form_submit_button("Catat Hutang", type="primary", use_container_width=True):
                if not nama_hutang or nominal_hutang <= 0:
                    st.warning("Isi nama hutang dan nominal lebih dari 0.")
                else:
                    hutang_baru = pd.DataFrame(
                        [
                            {
                                "username": CURRENT_USER,
                                "id": str(uuid.uuid4())[:8],
                                "tanggal": str(tgl_hutang),
                                "asal_hutang": asal_hutang,
                                "jenis_hutang": jenis_hutang,
                                "nama_hutang": nama_hutang.strip(),
                                "pemberi_pinjaman": pemberi if pemberi else "-",
                                "total_hutang": nominal_hutang,
                                "sudah_dibayar": 0.0,
                                "status": "Belum Lunas",
                                "keterangan": ket_hutang if ket_hutang else "-",
                            }
                        ]
                    )
                    df_hutang = pd.concat([df_hutang, hutang_baru], ignore_index=True)
                    save_user_df("hutang", df_hutang, KOLOM_HUTANG, CURRENT_USER)
                    st.success(f"{asal_hutang} **{nama_hutang}** ({jenis_hutang}) berhasil dicatat!")
                    st.rerun()

    with col_h2:
        st.subheader("Bayar Cicilan / Pelunasan Hutang")
        hutang_aktif = df_hutang[df_hutang["status"] != "Lunas"] if not df_hutang.empty else pd.DataFrame()

        if hutang_aktif.empty:
            st.info("Tidak ada hutang aktif yang perlu dibayar.")
        else:
            opsi_hutang = {
                f"[{row['jenis_hutang']}] {row['nama_hutang']} — Sisa: {format_rp(row['total_hutang'] - row['sudah_dibayar'])}": row["id"]
                for _, row in hutang_aktif.iterrows()
            }
            daftar_akun_bayar = df_aset["nama_akun"].tolist() if not df_aset.empty else ["Umum"]

            with st.form("form_bayar_hutang", clear_on_submit=True):
                pilih_label = st.selectbox("Pilih Hutang", list(opsi_hutang.keys()))
                tgl_bayar = st.date_input("Tanggal Bayar", value=date.today())
                nominal_bayar = input_nominal(
                    "Nominal Pembayaran (Rp)",
                    value=0.0,
                    key="input_nominal_bayar_hutang",
                    placeholder="Contoh: 1,500,000",
                )
                potong_kas = st.checkbox("Otomatis potong dari Saldo / Akun", value=True)
                sumber_bayar = st.selectbox("Sumber Dana Pembayaran", daftar_akun_bayar)

                if st.form_submit_button("Simpan Pembayaran", use_container_width=True):
                    if nominal_bayar <= 0:
                        st.warning("Nominal pembayaran harus lebih dari 0.")
                    else:
                        target_id = opsi_hutang[pilih_label]
                        idx = df_hutang.index[df_hutang["id"] == target_id][0]
                        nama_h = df_hutang.at[idx, "nama_hutang"]

                        df_hutang.at[idx, "sudah_dibayar"] += nominal_bayar
                        if df_hutang.at[idx, "sudah_dibayar"] >= df_hutang.at[idx, "total_hutang"]:
                            df_hutang.at[idx, "status"] = "Lunas"
                        save_user_df("hutang", df_hutang, KOLOM_HUTANG, CURRENT_USER)

                        if potong_kas:
                            trx_bayar = pd.DataFrame(
                                [
                                    {
                                        "username": CURRENT_USER,
                                        "id": str(uuid.uuid4())[:8],
                                        "tanggal": str(tgl_bayar),
                                        "jenis": "Pengeluaran",
                                        "akun_saldo": sumber_bayar,
                                        "kategori": "Cicilan / Bayar Hutang",
                                        "nominal": nominal_bayar,
                                        "keterangan": f"Bayar hutang: {nama_h}",
                                    }
                                ]
                            )
                            df_transaksi = pd.concat([df_transaksi, trx_bayar], ignore_index=True)
                            save_user_df("transaksi", df_transaksi, KOLOM_TRANSAKSI, CURRENT_USER)

                        st.success(f"Pembayaran **{nama_h}** sebesar {format_rp(nominal_bayar)} tercatat!")
                        st.rerun()

    st.divider()
    st.subheader("Daftar Hutang")
    if df_hutang.empty:
        st.write("Belum ada catatan hutang.")
    else:
        tampil_h = df_hutang.copy()
        tampil_h["sisa_hutang"] = (tampil_h["total_hutang"] - tampil_h["sudah_dibayar"]).clip(lower=0)
        for kol in ["total_hutang", "sudah_dibayar", "sisa_hutang"]:
            tampil_h[kol] = tampil_h[kol].map(format_rp)

        st.dataframe(
            tampil_h[
                [
                    "asal_hutang",
                    "jenis_hutang",
                    "nama_hutang",
                    "pemberi_pinjaman",
                    "total_hutang",
                    "sudah_dibayar",
                    "sisa_hutang",
                    "status",
                ]
            ].rename(
                columns={
                    "asal_hutang": "Asal",
                    "jenis_hutang": "Jenis",
                    "nama_hutang": "Nama Hutang",
                    "pemberi_pinjaman": "Lembaga",
                    "total_hutang": "Total Hutang",
                    "sudah_dibayar": "Sudah Dibayar",
                    "sisa_hutang": "Sisa Hutang",
                    "status": "Status",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

# --- TAB 4: GRAFIK & ANALISIS ---
with tab4:
    g1, g2 = st.columns(2)

    with g1:
        st.subheader("Komposisi Aset / Saldo per Jenis")
        if not df_aset.empty and df_aset["saldo_saat_ini"].sum() > 0:
            fig_aset = px.pie(
                df_aset[df_aset["saldo_saat_ini"] > 0],
                values="saldo_saat_ini",
                names="jenis_saldo",
                hole=0.35,
                color_discrete_sequence=px.colors.qualitative.Vivid,
            )
            fig_aset.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig_aset, use_container_width=True)
        else:
            st.info("Belum ada data saldo/aset.")

    with g2:
        st.subheader("Komposisi Sisa Hutang per Jenis")
        if not df_hutang.empty:
            df_h_chart = df_hutang.copy()
            df_h_chart["sisa_hutang"] = (df_h_chart["total_hutang"] - df_h_chart["sudah_dibayar"]).clip(lower=0)
            df_h_chart = df_h_chart[df_h_chart["sisa_hutang"] > 0]
            if not df_h_chart.empty:
                fig_hutang = px.pie(
                    df_h_chart,
                    values="sisa_hutang",
                    names="jenis_hutang",
                    hole=0.35,
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                fig_hutang.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_hutang, use_container_width=True)
            else:
                st.info("Semua hutang sudah lunas!")
        else:
            st.info("Belum ada data hutang.")

    st.divider()
    g3, g4 = st.columns(2)
    with g3:
        st.subheader("Pengeluaran per Kategori")
        df_keluar = df_transaksi[df_transaksi["jenis"] == "Pengeluaran"] if not df_transaksi.empty else pd.DataFrame()
        if not df_keluar.empty:
            fig_keluar = px.bar(
                df_keluar.groupby("kategori", as_index=False)["nominal"].sum(),
                x="kategori",
                y="nominal",
                color="kategori",
                text_auto=True,
            )
            st.plotly_chart(fig_keluar, use_container_width=True)
        else:
            st.info("Belum ada data pengeluaran.")

    with g4:
        st.subheader("Pendapatan per Kategori")
        df_masuk = df_transaksi[df_transaksi["jenis"] == "Pendapatan"] if not df_transaksi.empty else pd.DataFrame()
        if not df_masuk.empty:
            fig_masuk = px.bar(
                df_masuk.groupby("kategori", as_index=False)["nominal"].sum(),
                x="kategori",
                y="nominal",
                color="kategori",
                text_auto=True,
            )
            st.plotly_chart(fig_masuk, use_container_width=True)
        else:
            st.info("Belum ada data pendapatan.")

# --- TAB 5: RIWAYAT, PRINT (MAKS. 30 HARI) & HAPUS ---
with tab5:
    st.subheader("Riwayat Transaksi & Cetak Laporan (Maks. 30 Hari)")
    if df_transaksi.empty:
        st.info("Belum ada transaksi.")
    else:
        df_view = df_transaksi.copy()

        # Filter rentang tanggal (default 30 hari terakhir)
        hari_ini = date.today()
        default_awal = hari_ini - timedelta(days=29)

        d1, d2, d3, d4 = st.columns(4)
        tgl_mulai = d1.date_input("Dari Tanggal", value=default_awal, key="filter_tgl_mulai")
        tgl_selesai = d2.date_input("Sampai Tanggal", value=hari_ini, key="filter_tgl_selesai")
        akun_pilih = d3.selectbox("Filter Akun", ["Semua"] + sorted(df_view["akun_saldo"].unique()))
        kat_pilih = d4.selectbox("Filter Kategori", ["Semua"] + sorted(df_view["kategori"].unique()))

        rentang_hari = (tgl_selesai - tgl_mulai).days

        if rentang_hari < 0:
            st.error("Tanggal akhir tidak boleh lebih kecil dari tanggal awal.")
        elif rentang_hari > 30:
            st.warning(
                f"Rentang yang dipilih **{rentang_hari} hari**. Maksimal tampilan dan cetak adalah **30 hari**. "
                "Silakan perkecil rentang tanggalnya ya, Bos!"
            )
        else:
            df_view = df_view[
                (df_view["tanggal"] >= tgl_mulai) & (df_view["tanggal"] <= tgl_selesai)
            ]
            if akun_pilih != "Semua":
                df_view = df_view[df_view["akun_saldo"] == akun_pilih]
            if kat_pilih != "Semua":
                df_view = df_view[df_view["kategori"] == kat_pilih]

            df_view = df_view.sort_values(by="tanggal", ascending=False)

            if df_view.empty:
                st.info("Tidak ada transaksi pada rentang tanggal & filter yang dipilih.")
            else:
                # Ringkasan periode terpilih
                p_masuk = df_view[df_view["jenis"] == "Pendapatan"]["nominal"].sum()
                p_keluar = df_view[df_view["jenis"] == "Pengeluaran"]["nominal"].sum()
                m1, m2, m3 = st.columns(3)
                m1.metric("Pendapatan Periode Ini", format_rp(p_masuk))
                m2.metric("Pengeluaran Periode Ini", format_rp(p_keluar))
                m3.metric("Selisih Periode Ini", format_rp(p_masuk - p_keluar))

                tampil_trx = df_view.copy()
                tampil_trx["nominal"] = tampil_trx["nominal"].map(format_rp)

                st.dataframe(
                    tampil_trx[["id", "tanggal", "jenis", "akun_saldo", "kategori", "nominal", "keterangan"]].rename(
                        columns={
                            "id": "ID",
                            "tanggal": "Tanggal",
                            "jenis": "Jenis",
                            "akun_saldo": "Akun",
                            "kategori": "Kategori",
                            "nominal": "Nominal",
                            "keterangan": "Keterangan",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                # Tombol Print & Download CSV
                btn_c1, btn_c2 = st.columns([1, 1])
                with btn_c1:
                    buat_tombol_print(df_view, CURRENT_USER, tgl_mulai, tgl_selesai)
                with btn_c2:
                    csv_data = df_view[
                        ["tanggal", "jenis", "akun_saldo", "kategori", "nominal", "keterangan"]
                    ].to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="📥 Download CSV Periode Ini",
                        data=csv_data,
                        file_name=f"laporan_{CURRENT_USER}_{tgl_mulai}_sd_{tgl_selesai}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                st.divider()
                st.markdown("#### Hapus Transaksi")
                id_hapus = st.selectbox("Pilih ID Transaksi yang ingin dihapus", df_view["id"].tolist())
                if st.button("Hapus Transaksi Terpilih", type="secondary"):
                    df_transaksi = df_transaksi[df_transaksi["id"] != id_hapus]
                    save_user_df("transaksi", df_transaksi, KOLOM_TRANSAKSI, CURRENT_USER)
                    st.success(f"Transaksi ID `{id_hapus}` berhasil dihapus.")
                    st.rerun()
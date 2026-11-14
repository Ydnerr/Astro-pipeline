# Astro Stack di GitHub Actions

Stacking foto langit malam (Milky Way, star trail) lewat GitHub Actions, dijalankan dari HP.

Dua tahap, bisa dipakai terpisah:

1. **Stacking** (`stack.py`): menyelaraskan bintang di banyak foto, lalu merata-ratakannya jadi satu gambar yang lebih bersih dari noise.
2. **Grading** ([astro-pipeline](https://github.com/howar31/astro-pipeline), MIT): mengolah hasil stack jadi gambar akhir (Milky Way lebih menonjol, bintang dirapikan).

## 1. Setup (sekali saja)

Repo ini harus berisi dua hal ini:

```
repo/
├── stack.py                          <- di root repo
└── .github/
    └── workflows/
        └── astro-pipeline.yml        <- di dalam folder .github/workflows/
```

Cara upload dari HP: buka repo di browser, **Add file → Upload files**, pilih `stack.py`, lalu **Commit changes**. Untuk yml, **Add file → Create new file**, ketik nama `.github/workflows/astro-pipeline.yml` (garis miring otomatis membuat folder), tempel isinya, lalu commit.

## 2. Struktur folder untuk tiap sesi foto

Satu sesi foto = satu folder. Nama folder bebas. Foto mentah (JPG) harus ada di subfolder bernama persis `frames`.

```
repo/
├── stack.py
├── .github/workflows/astro-pipeline.yml
└── sesi1/                  <- folder sesi, boleh pakai nama lain
    └── frames/             <- WAJIB bernama "frames"
        ├── IMG_001.jpg
        ├── IMG_002.jpg
        └── ...
```

Yang **diketik di form** nanti adalah nama folder sesi (`sesi1`), **bukan** `sesi1/frames`.

File opsional di folder sesi yang sama:

| File | Fungsi |
| --- | --- |
| `mask.png` | Mask langit buatan sendiri. Putih = langit, hitam = foreground. Dipakai kalau pilihan mask = `file-mask.png`. |
| `<nama>_GraXpert.tiff` | Hanya untuk foto langit murni (tanpa foreground), saat grading. `<nama>` = nama folder sesi. |

Upload foto lewat browser dibatasi 25 MB per file dan 100 file per sekali upload. Kalau lebih dari 100 foto, upload bertahap.

## 3. Coba dulu dengan contoh

Pakai `contoh-frames.zip` (13 gambar sintetis buatan, bukan foto langit asli).

1. Ekstrak zip-nya. Hasilnya folder `contoh/frames/` berisi `f000.jpg` sampai `f012.jpg`.
2. Upload folder `contoh` ke repo, sejajar dengan `stack.py`.
3. Buka tab **Actions** → **Astro Pipeline** → **Run workflow**.
4. Isi form persis seperti ini:

| Kolom | Isi |
| --- | --- |
| folder | `contoh` |
| stage | `stack-saja` |
| mask | `auto` |
| resize | `1.0` |

   Kolom lainnya biarkan default. Tekan **Run workflow**.
5. Tunggu sampai run hijau (biasanya kurang dari 2 menit).
6. Buka run-nya, scroll ke bawah ke bagian **Artifacts**, lalu unduh `astro-out-...`. Isinya `contoh.tif` (hasil stack) dan `mask_auto.png` (mask tebakan; foreground gelap di bagian bawah harusnya terlihat hitam).

Untuk data contoh ini jangan pilih `stack-lalu-grade`. Grading butuh Milky Way asli, jadi di data sintetis ia akan berhenti dengan pesan bahwa tidak ada Milky Way.

## 4. Pakai foto sendiri

1. Upload foto ke `<folder sesi>/frames/` (lihat bagian 2).
2. **Actions → Astro Pipeline → Run workflow**.
3. Isi form sesuai tabel di bawah.
4. Hasil ada di **Artifacts** pada halaman run. Kalau `commit_back` dicentang, JPG akhirnya juga masuk ke repo di `<folder sesi>/astro_out/<nama>_graded_starreduce2.jpg`.

### Isi form

| Kolom | Pilihan | Artinya |
| --- | --- | --- |
| **folder** | teks, mis. `sesi1` | Folder sesi. Bukan `sesi1/frames`. |
| **stage** | `stack-lalu-grade` | Stacking, lalu grading. Pakai ini untuk foto langit asli dari awal sampai akhir. |
| | `grade-saja` | Hanya grading. Butuh `<nama>.tif` yang sudah ada di folder sesi (hasil stack sebelumnya atau dari Sequator). |
| | `stack-saja` | Hanya stacking. Hasil: `<nama>.tif`. |
| | `trail-saja` | Star trail (ambil piksel paling terang dari semua frame, tanpa align). Hasil: `<nama>_trail.tif`. |
| **mask** | `tanpa` | Semua piksel di-align mengikuti bintang. Foreground (pohon, bukit) akan blur. Cocok untuk foto tanpa foreground. |
| | `auto` | Menebak foreground dari area yang gelap. Mask yang dipakai disimpan sebagai `mask_auto.png` di artifact supaya bisa dicek. |
| | `file-mask.png` | Memakai `mask.png` buatan sendiri di folder sesi. Run gagal kalau file-nya tidak ada. |
| **resize** | `1.0` / `0.75` / `0.5` | Skala frame saat stacking. Makin kecil makin hemat RAM, tapi hasilnya ikut mengecil. |
| **milkyway** | `auto` / `yes` / `no` | Pilih `yes` atau `no` hanya kalau pipeline sebelumnya berhenti dengan "Milky Way detection uncertain". |
| **mode** | `auto` / `sky` / `landscape` | Pilih hanya kalau pipeline berhenti dengan "landscape detection uncertain". |
| **look** | `default`, `stronger-milkyway`, `softer-milkyway`, `smoother-nebula`, `emptier-stars`, `keep-more-stars`, `darker-sky`, `brighter-sky`, `less-saturated` | Preset tampilan hasil grading. |
| **pipeline** | `display` / `legacy` | Biarkan `display`. |
| **extra_set** | teks, mis. `band_bright=0.6 melt=0.8` | Override manual, opsional. Hanya huruf, angka, `_ = . -` dan spasi. |
| **commit_back** | centang / tidak | Simpan JPG akhir ke repo. |

## 5. Kalau run berhenti dengan STOP

GitHub Actions tidak bisa bertanya di tengah run. Jadi kalau pipeline tidak yakin, run berakhir merah dan halaman **Summary** menjelaskan apa yang harus dipilih. Lalu **Run workflow** lagi dengan pilihan itu.

| Pesan STOP | Yang dipilih di form |
| --- | --- |
| Milky Way detection uncertain | milkyway = `yes` atau `no` |
| landscape detection uncertain | mode = `landscape` atau `sky` |
| `<nama>_GraXpert.tiff` not found | Upload file itu ke folder sesi, jalankan lagi |
| no Milky Way in this frame | Frame di luar cakupan, tidak ada yang dibuat |

Hasil stacking dari run yang berhenti tidak disimpan, jadi stacking ikut diulang pada run berikutnya.

## 6. Kalau gagal

Buka run yang merah, lalu buka langkah **Stacking dan grading** dan cari baris yang diawali `Error:`.

| Pesan | Penyebab dan perbaikan |
| --- | --- |
| `Folder '...' tidak ada di repo` | Salah ketik atau salah huruf besar-kecil di kolom folder. |
| `Frame mentah harus ada di '.../frames'` | Subfolder `frames` tidak ada. Sering terjadi karena kolom folder diisi `sesi1/frames`; yang benar `sesi1`. |
| `stack.py tidak ada di root repo` | `stack.py` belum diupload, atau ada di dalam folder. |
| `... tidak ada. Jalankan stacking dulu ...` | Stage `grade-saja` dipilih, tapi `<nama>.tif` belum ada di folder sesi. |
| `Pilih file-mask.png tapi ... tidak ada` | `mask.png` belum diupload ke folder sesi. |
| `hanya 1 frame yang berhasil di-align` atau `... bintang terdeteksi` | Foto bukan foto bintang, terlalu terang atau gelap, atau frame berbeda terlalu jauh. |
| Peringatan soal `ffmpeg` | Abaikan. ffmpeg hanya untuk fitur video, yang tidak dipakai di sini. |
| `git push` gagal (403) | **Settings → Actions → General → Workflow permissions**, pilih **Read and write**. |

Di langkah stacking ada log per frame: `N inlier, rms X px`. Kalau `rms` di bawah 1 px, alignment-nya baik.

## 7. Batasan

- `stack.py` baru diuji dengan gambar sintetis, **belum dengan foto langit asli**. Lensa yang distorsi, hot pixel, awan, dan satelit bisa memengaruhi hasil. Coba dulu dengan 10-20 foto.
- Hanya JPG, PNG, dan TIFF. **RAW belum didukung.**
- Mode `average` saja (tidak ada median atau sigma-clip).
- `auto` mask adalah heuristik: cuma mengenali foreground yang gelap. Foreground yang terkena cahaya bisa meleset; buat `mask.png` sendiri.
- Langit murni (tanpa foreground) butuh file hasil GraXpert yang dibuat manual di luar repo ini.
- Kompatibilitas TIFF hasil `stack.py` dengan astro-pipeline belum dipastikan. Hasil berupa TIFF RGB 16-bit terkompresi zlib.
- Memori: sekitar 1,5 sampai 2 GB untuk foto 24 MP (perkiraan). Gunakan `resize` 0.5 kalau kehabisan RAM.

## Kredit

- Grading memakai [astro-pipeline](https://github.com/howar31/astro-pipeline) oleh howar31 (lisensi MIT), di-checkout otomatis saat workflow berjalan.
- `stack.py` ditulis dari nol memakai numpy, OpenCV, dan tifffile. Tidak ada kode dari Sequator.

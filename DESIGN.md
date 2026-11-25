# DESIGN.md — RAGMON (Pixelated Sunset Theme)

> **Design Read:** Reading this as: Retro 16-bit pixel RPG PDF knowledge-base chat workspace for AI engineers, inspired by the twilight-to-cream sunset pixel palette, dial ENERGY 3 / RHYTHM 2 / MOTION 1.

## 1. Visual Identity & Color Palette (R-01, R-29, R-31)
- **Referensi Palet:** Twilight Violet (`#4c1d95`), Sunset Magenta (`#db4c8f`), Warm Peach (`#ea8c55`), dan Pixel Ink (`#1b1035`), dipadukan adaptif dengan `var(--background-color)`, `var(--secondary-background-color)`, dan `var(--text-color)` Streamlit agar mode *Light* dan *Dark* di menu `⋮` tetap terbaca tajam.
- **Latar Belakang:** Gradasi vertikal langit senja halus (menggunakan `linear-gradient` transparan di atas `var(--background-color)`) dengan pola *pixel dither* tipis `2px x 2px` sebagai motif identitas tema piksel.

## 2. Pixel Geometry, Borders & Elevation (R-10, R-11, R-12)
- **Sharp Pixel Corners:** Seluruh komponen utama (Hero Card, Chat Bubble, Button, Input Bar, PDF Card, Tag) memakai `border-radius: 0px` dengan border solid `2px` (`currentColor` / aksen).
- **Hard Pixel Shadow:** Menggunakan bayangan tegas tanpa blur (`4px 4px 0px`) pada Hero Card, Chat Bubble, dan Chat Input agar terasa seperti kotak dialog game retro.
- **Avatar:** Gambar avatar Mon-chan dirender dengan `image-rendering: pixelated` dan bingkai piksel `2px`.

## 3. Typography (R-06)
- **Pixel Display (`Silkscreen`):** Dipakai pada judul utama, heading sidebar, tombol aksi, dan tag teknologi untuk karakter 8-bit/16-bit yang tegas.
- **Pixel Body (`Pixelify Sans`):** Dipakai pada seluruh isi chat, input teks, label, dan bukti kutipan agar seluruh antarmuka konsisten bertema piksel namun tetap nyaman dibaca pada paragraf panjang.

## 4. Accessibility & Mobile Reflow (R-03, R-25, R-32, R-39)
- Seluruh tombol aksi utama memenuhi `min-height: 44px`, `:focus-visible` memakai outline `2px solid`, dan animasi/transisi dinonaktifkan di bawah `prefers-reduced-motion: reduce`.
- Pada layar `<= 640px`, bubble chat melebar hingga `92%` tanpa *horizontal overflow*.

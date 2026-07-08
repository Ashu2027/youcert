# Youcert

Youcert is an AI-powered certification and interactive learning platform tailored for video content creators (like YouTubers). It enables creators to upload full playlists or massive educational videos, automatically processes them to generate intelligent quizzes based on Bloom's Taxonomy, and issues verified certificates to their learners upon successful completion.

## 🚀 Features
- **AI-Powered Quiz Generation**: Automatically analyzes video transcripts and generates context-aware questions using Google's Gemini AI, dynamically distributing difficulty across different cognitive levels (Bloom's Taxonomy).
- **Massive Scale Processing**: Robust background processing using Cloudflare Queues that can convert full playlists or incredibly long videos (up to 100 hours) into comprehensive certification exams.
- **Audience Certification**: A dedicated pipeline allowing the learners and subscribers of a YouTuber to officially test their knowledge and earn digital certificates.
- **Creator Dashboard**: Creators can easily manage their courses, track student performance, and monitor their revenue and earnings.
- **Payment Integration**: Seamless course enrollments and certificate processing powered by Razorpay.
- **Secure Media Delivery**: Fast and secure video and file serving using Cloudflare R2 storage.
- **Automated Communications**: Sends generated certificates and transactional emails instantly via ZeptoMail.
- **Role-Based Admin Access**: Multi-tier hierarchical permission system (Supreme, Chief, Major, Hero) for platform administration.

## 🛠️ Technology Stack
- **Core Backend**: Python, Flask, Gunicorn (with Gevent concurrency)
- **Database**: TiDB (MySQL compatible)
- **Edge Deployment**: Cloudflare Workers & Containers
- **Object Storage**: Cloudflare R2
- **AI Provider**: Google Vertex AI (Gemini)

## ⚖️ License & Usage

**Custom Source-Available License**

The source code for Youcert is provided open and accessible for transparency and learning.

Individual content creators (e.g., YouTubers, educators) are granted a free license to self-host and modify this software exclusively for their own personal audience and learners. However, no entity may host, distribute, or offer this software as a service (SaaS) to third-party creators, nor use it to build a competing commercial platform without explicit written permission.

**For Business Licensing:** If you are a business entity interested in commercial usage, please contact me directly at ashutoshbhunia01@gmail.com.

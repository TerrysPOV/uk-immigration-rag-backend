#!/usr/bin/env python3
"""
Autonomous Document Scraping & Processing Orchestrator

Runs unattended for ~8 hours to complete all document scraping and processing.

Strategy:
1. Monitor current processing completion (302 docs with content)
2. Scrape in batches of 500 documents
3. Wait for processing queue to drain between batches
4. Monitor memory/CPU health continuously
5. Auto-stop if resources become critical
6. Generate final completion report

Expected Timeline:
- 18 batches × (17min scrape + 10min process) = ~8 hours
- Total documents to scrape: 8,749 (9,051 - 302 already done)
"""
import sys
sys.path.insert(0, '/opt/gov-ai/backend')

import psycopg2
import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import time
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
import subprocess
import re

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/opt/gov-ai/logs/autonomous_orchestrator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 250  # Reduced from 500 to be safer
DELAY_BETWEEN_REQUESTS = 2.0  # seconds
MAX_PROCESSING_QUEUE_SIZE = 1000  # Wait if queue exceeds this (reduced from 2000)
MEMORY_CRITICAL_THRESHOLD_MB = 800  # Stop if available memory drops below this (was 500, accounting for FastAPI restarts)
HEALTH_CHECK_INTERVAL = 300  # Check resources every 5 minutes
MAX_RUNTIME_HOURS = 10  # Emergency stop after 10 hours

class SystemHealth:
    """Monitor droplet health"""

    @staticmethod
    def get_memory_stats():
        """Get memory usage in MB"""
        result = subprocess.run(['free', '-m'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        mem_line = [l for l in lines if l.startswith('Mem:')][0]
        parts = mem_line.split()
        return {
            'total': int(parts[1]),
            'used': int(parts[2]),
            'free': int(parts[3]),
            'available': int(parts[6])
        }

    @staticmethod
    def get_load_average():
        """Get system load average"""
        with open('/proc/loadavg', 'r') as f:
            load = f.read().split()[0:3]
        return float(load[0])

    @staticmethod
    def is_healthy():
        """Check if system is healthy enough to continue"""
        mem = SystemHealth.get_memory_stats()
        load = SystemHealth.get_load_average()

        if mem['available'] < MEMORY_CRITICAL_THRESHOLD_MB:
            logger.error(f"CRITICAL: Available memory {mem['available']}MB < {MEMORY_CRITICAL_THRESHOLD_MB}MB")
            return False

        if load > 2.0:
            logger.warning(f"HIGH LOAD: {load} (threshold 2.0)")
            return False

        return True

class Database:
    """Database operations"""

    @staticmethod
    def get_connection():
        return psycopg2.connect(
            dbname="gov_ai_db",
            user="postgres",
            password="postgres",
            host="localhost"
        )

    @staticmethod
    def get_stats():
        """Get current processing stats"""
        conn = Database.get_connection()
        cur = conn.cursor()

        # Document stats
        cur.execute("""
            SELECT
                COUNT(*) as total_docs,
                COUNT(*) FILTER (WHERE content IS NOT NULL AND LENGTH(content) > 0) as with_content,
                COUNT(*) FILTER (WHERE processing_success = true) as processed
            FROM documents
        """)
        doc_stats = cur.fetchone()

        # Queue stats
        cur.execute("""
            SELECT status, COUNT(*)
            FROM processing_queue
            GROUP BY status
        """)
        queue_stats = dict(cur.fetchall())

        cur.close()
        conn.close()

        return {
            'total_docs': doc_stats[0],
            'with_content': doc_stats[1],
            'processed': doc_stats[2],
            'queue_pending': queue_stats.get('pending', 0),
            'queue_processing': queue_stats.get('processing', 0),
            'queue_completed': queue_stats.get('completed', 0),
            'queue_failed': queue_stats.get('failed', 0)
        }

    @staticmethod
    def get_documents_to_scrape(batch_size):
        """Get next batch of documents needing content"""
        conn = Database.get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, url
            FROM documents
            WHERE content IS NULL OR LENGTH(content) = 0
            ORDER BY id ASC
            LIMIT %s
        """, (batch_size,))

        docs = cur.fetchall()
        cur.close()
        conn.close()

        return docs

    @staticmethod
    def save_document_content(doc_id, url, content):
        """Save scraped content and queue for processing"""
        conn = Database.get_connection()
        cur = conn.cursor()

        try:
            # Save content
            cur.execute("""
                UPDATE documents
                SET content = %s
                WHERE id = %s
            """, (content, doc_id))

            # Queue for processing
            cur.execute("""
                INSERT INTO processing_queue (document_id, url, status, priority)
                SELECT document_id, url, 'pending', 50
                FROM documents
                WHERE id = %s
                ON CONFLICT DO NOTHING
            """, (doc_id,))

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save doc {doc_id}: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()
            conn.close()

class Scraper:
    """Document scraping with PDF extraction"""

    @staticmethod
    def extract_pdf_text(pdf_url):
        """Download and extract text from PDF"""
        try:
            logger.info(f"   📄 Downloading PDF: {pdf_url[:80]}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (UK Government Document Processor)',
                'Accept': 'application/pdf'
            }

            response = requests.get(pdf_url, headers=headers, timeout=60)
            response.raise_for_status()

            pdf_file = io.BytesIO(response.content)
            text_parts = []

            with pdfplumber.open(pdf_file) as pdf:
                page_count = len(pdf.pages)

                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

            full_text = '\n\n'.join(text_parts)
            logger.info(f"   ✅ Extracted {len(full_text):,} chars from {page_count}-page PDF")

            return full_text

        except Exception as e:
            logger.error(f"   ❌ PDF extraction failed: {e}")
            return ""

    @staticmethod
    def find_pdf_links(soup, base_url):
        """Find all PDF links on the page"""
        pdf_links = []

        for link in soup.find_all('a', href=True):
            href = link['href']

            if href.endswith('.pdf') or '/attachment/' in href or 'format=pdf' in href.lower():
                full_url = urljoin(base_url, href)

                if 'gov.uk' in full_url:
                    pdf_links.append(full_url)

        return list(set(pdf_links))[:5]  # Limit to 5 PDFs

    @staticmethod
    def fetch_comprehensive_content(url):
        """Fetch HTML + nested PDFs"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (UK Government Document Processor)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

            # Find PDFs
            pdf_links = Scraper.find_pdf_links(soup, url)

            stats = {
                'html_chars': len(html_content),
                'pdf_count': len(pdf_links),
                'pdf_chars': 0
            }

            # Extract PDFs
            pdf_texts = []

            if pdf_links:
                logger.info(f"   Found {len(pdf_links)} PDFs to extract")

                for pdf_url in pdf_links:
                    pdf_text = Scraper.extract_pdf_text(pdf_url)

                    if pdf_text:
                        pdf_texts.append(f"\n\n--- PDF CONTENT: {pdf_url} ---\n\n{pdf_text}")
                        stats['pdf_chars'] += len(pdf_text)

                    time.sleep(0.5)  # Rate limit PDF downloads

            # Combine
            combined_content = html_content

            if pdf_texts:
                combined_content += '\n\n=== NESTED PDF DOCUMENTS ===\n' + '\n'.join(pdf_texts)

            stats['total_chars'] = len(combined_content)

            return combined_content, stats

        except Exception as e:
            logger.error(f"   ❌ Fetch failed: {e}")
            return None, {'error': str(e)}

class Orchestrator:
    """Main orchestration logic"""

    def __init__(self):
        self.start_time = datetime.now()
        self.total_scraped = 0
        self.total_failed = 0
        self.total_pdfs = 0
        self.batch_number = 0

    def wait_for_queue_drain(self, max_pending=MAX_PROCESSING_QUEUE_SIZE, timeout_minutes=30):
        """Wait for processing queue to drain below threshold"""
        logger.info(f"\n⏳ Waiting for queue to drain below {max_pending} pending jobs...")

        start_wait = datetime.now()

        while True:
            stats = Database.get_stats()
            pending = stats['queue_pending']
            processing = stats['queue_processing']

            logger.info(f"   Queue: {pending} pending, {processing} processing")

            if pending <= max_pending:
                logger.info(f"✅ Queue drained to {pending} pending jobs")
                return True

            # Timeout check
            elapsed = (datetime.now() - start_wait).total_seconds() / 60
            if elapsed > timeout_minutes:
                logger.warning(f"⚠️ Queue drain timeout after {elapsed:.1f} minutes")
                return False

            # Health check
            if not SystemHealth.is_healthy():
                logger.error("❌ System unhealthy during queue wait")
                return False

            time.sleep(30)  # Check every 30 seconds

    def scrape_batch(self, batch_size):
        """Scrape one batch of documents"""
        self.batch_number += 1

        logger.info(f"\n{'='*80}")
        logger.info(f"📦 BATCH {self.batch_number}: Scraping {batch_size} documents")
        logger.info(f"{'='*80}")

        docs = Database.get_documents_to_scrape(batch_size)

        if not docs:
            logger.info("✅ No more documents to scrape!")
            return False

        logger.info(f"Found {len(docs)} documents to scrape")

        batch_scraped = 0
        batch_failed = 0
        batch_pdfs = 0

        for idx, (doc_id, url) in enumerate(docs, 1):
            logger.info(f"\n[{idx}/{len(docs)}] Doc ID: {doc_id}")
            logger.info(f"🌐 Fetching: {url[:80]}")

            # Fetch content
            content, stats = Scraper.fetch_comprehensive_content(url)

            if content and len(content) >= 100:
                # Save to database
                if Database.save_document_content(doc_id, url, content):
                    batch_scraped += 1
                    self.total_scraped += 1

                    if stats.get('pdf_count', 0) > 0:
                        batch_pdfs += stats['pdf_count']
                        self.total_pdfs += stats['pdf_count']
                        logger.info(f"   ✅ SAVED: {stats['total_chars']:,} chars ({stats['pdf_count']} PDFs)")
                    else:
                        logger.info(f"   ✅ SAVED: {stats['total_chars']:,} chars")
                else:
                    batch_failed += 1
                    self.total_failed += 1
                    logger.warning(f"   ❌ SAVE FAILED")
            else:
                batch_failed += 1
                self.total_failed += 1
                logger.warning(f"   ❌ FETCH FAILED")

            # Rate limiting
            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Health check every 50 docs
            if idx % 50 == 0:
                if not SystemHealth.is_healthy():
                    logger.error("❌ System unhealthy during scraping - stopping batch")
                    break

        # Batch summary
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 BATCH {self.batch_number} COMPLETE")
        logger.info(f"   ✅ Scraped: {batch_scraped}")
        logger.info(f"   📄 PDFs: {batch_pdfs}")
        logger.info(f"   ❌ Failed: {batch_failed}")
        logger.info(f"{'='*80}\n")

        return True

    def run(self):
        """Main orchestration loop"""
        logger.info(f"\n{'#'*80}")
        logger.info(f"🚀 AUTONOMOUS ORCHESTRATOR STARTED")
        logger.info(f"   Start Time: {self.start_time}")
        logger.info(f"   Max Runtime: {MAX_RUNTIME_HOURS} hours")
        logger.info(f"   Batch Size: {BATCH_SIZE} documents")
        logger.info(f"{'#'*80}\n")

        try:
            # Step 1: Wait for existing 302 documents to process
            logger.info("📊 STEP 1: Waiting for existing documents to process...")
            stats = Database.get_stats()
            logger.info(f"   Documents with content: {stats['with_content']}")
            logger.info(f"   Processing queue: {stats['queue_pending']} pending, {stats['queue_processing']} processing")

            if stats['queue_pending'] > 100:
                self.wait_for_queue_drain(max_pending=100, timeout_minutes=20)

            # Step 2: Batch scraping loop
            logger.info("\n📊 STEP 2: Starting batch scraping loop...")

            while True:
                # Runtime check
                elapsed = datetime.now() - self.start_time
                if elapsed.total_seconds() / 3600 > MAX_RUNTIME_HOURS:
                    logger.warning(f"⚠️ Max runtime {MAX_RUNTIME_HOURS}h exceeded - stopping")
                    break

                # Health check
                if not SystemHealth.is_healthy():
                    logger.error("❌ System unhealthy - stopping")
                    break

                # Scrape batch
                if not self.scrape_batch(BATCH_SIZE):
                    logger.info("✅ All documents scraped!")
                    break

                # Wait for queue to drain before next batch
                self.wait_for_queue_drain(max_pending=MAX_PROCESSING_QUEUE_SIZE, timeout_minutes=30)

            # Step 3: Final wait for all processing to complete
            logger.info("\n📊 STEP 3: Waiting for final processing to complete...")
            self.wait_for_queue_drain(max_pending=0, timeout_minutes=60)

            # Generate final report
            self.generate_final_report()

        except Exception as e:
            logger.error(f"💥 ORCHESTRATOR EXCEPTION: {e}", exc_info=True)
            self.generate_final_report()

    def generate_final_report(self):
        """Generate completion report"""
        end_time = datetime.now()
        duration = end_time - self.start_time

        stats = Database.get_stats()
        mem = SystemHealth.get_memory_stats()
        load = SystemHealth.get_load_average()

        report = f"""
{'='*80}
🎉 AUTONOMOUS ORCHESTRATOR COMPLETE
{'='*80}

⏱️  TIMING
   Start Time:     {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}
   End Time:       {end_time.strftime('%Y-%m-%d %H:%M:%S')}
   Duration:       {duration.total_seconds() / 3600:.2f} hours

📊 SCRAPING STATS
   Batches:        {self.batch_number}
   Scraped:        {self.total_scraped:,} documents
   Failed:         {self.total_failed:,} documents
   PDFs Extracted: {self.total_pdfs:,} documents with PDFs

📄 DOCUMENT STATS
   Total Docs:     {stats['total_docs']:,}
   With Content:   {stats['with_content']:,} ({stats['with_content']/stats['total_docs']*100:.1f}%)
   Processed:      {stats['processed']:,} ({stats['processed']/stats['total_docs']*100:.1f}%)

📋 PROCESSING QUEUE
   Pending:        {stats['queue_pending']:,}
   Processing:     {stats['queue_processing']:,}
   Completed:      {stats['queue_completed']:,}
   Failed:         {stats['queue_failed']:,}

💻 SYSTEM HEALTH
   Memory Used:    {mem['used']}MB / {mem['total']}MB ({mem['used']/mem['total']*100:.1f}%)
   Memory Avail:   {mem['available']}MB
   Load Average:   {load}

{'='*80}
"""

        logger.info(report)

        # Save report to file
        with open('/opt/gov-ai/logs/orchestrator_final_report.txt', 'w') as f:
            f.write(report)

if __name__ == '__main__':
    orchestrator = Orchestrator()
    orchestrator.run()

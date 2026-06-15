#!/usr/bin/env python3
"""Read-only Instahyre opportunities DOM probe. Does not modify scraper."""
from __future__ import annotations

import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import paths

AUTH = str(paths.instahyre_auth_json())
FEED_URL = (
    "https://www.instahyre.com/candidate/opportunities/?matching=true"
)

PROBE_JS = """
() => {
  const jobRe = /\\/job-(\\d+)(?:\\/|$|-)/i;
  const root =
    document.querySelector('main') ||
    document.querySelector('[class*="opportunit"]') ||
    document.body;

  const allAnchors = Array.from(root.querySelectorAll('a[href]'));
  const jobAnchors = allAnchors.filter((a) => jobRe.test(a.getAttribute('href') || ''));
  const viewAnchors = allAnchors.filter((a) => (a.innerText || '').toLowerCase().includes('view'));
  const viewJobAnchors = jobAnchors.filter((a) => (a.innerText || '').toLowerCase().includes('view'));

  const buttons = Array.from(root.querySelectorAll('button'));
  const viewButtons = buttons.filter((b) => (b.innerText || '').toLowerCase().includes('view'));

  const motionDivs = root.querySelectorAll('motion.div').length;
  const sampleJobAnchors = jobAnchors.slice(0, 5).map((a) => ({
    href: a.getAttribute('href'),
    text: (a.innerText || '').slice(0, 80),
    tag: a.tagName,
    cls: (a.className || '').toString().slice(0, 120),
  }));
  const sampleViewButtons = viewButtons.slice(0, 5).map((b) => ({
    text: (b.innerText || '').slice(0, 80),
    type: b.getAttribute('type'),
    cls: (b.className || '').toString().slice(0, 120),
    onclick: !!b.onclick,
    role: b.getAttribute('role'),
  }));

  // Card-like blocks: repeated siblings with substantial text
  const candidates = Array.from(root.querySelectorAll('motion.div, article, li, div'))
    .filter((el) => {
      const t = (el.innerText || '').trim();
      return t.length > 120 && t.length < 3500 && /product|manager|engineer|developer/i.test(t);
    })
    .slice(0, 3)
    .map((el) => ({
      tag: el.tagName,
      cls: (el.className || '').toString().slice(0, 160),
      textHead: (el.innerText || '').trim().slice(0, 200),
      jobLinksInside: Array.from(el.querySelectorAll('a[href]'))
        .slice(0, 6)
        .map((a) => ({ href: a.getAttribute('href'), text: (a.innerText || '').slice(0, 40) })),
      buttonsInside: Array.from(el.querySelectorAll('button'))
        .slice(0, 4)
        .map((b) => ({ text: (b.innerText || '').slice(0, 40), type: b.getAttribute('type') })),
    }));

  return {
    url: location.href,
    rootTag: root.tagName,
    rootCls: (root.className || '').toString().slice(0, 160),
    counts: {
      allAnchors: allAnchors.length,
      jobAnchors: jobAnchors.length,
      viewAnchors: viewAnchors.length,
      viewJobAnchors: viewJobAnchors.length,
      buttons: buttons.length,
      viewButtons: viewButtons.length,
      motionDivs,
    },
    sampleJobAnchors,
    sampleViewButtons,
    cardCandidates: candidates,
    harvestStrict: (() => {
      const seen = new Set();
      let n = 0;
      for (const a of allAnchors) {
        const rawHref = a.getAttribute('href') || '';
        const m = rawHref.match(jobRe);
        if (!m) continue;
        if (seen.has(m[1])) continue;
        const linkText = (a.innerText || '').trim().toLowerCase();
        if (!linkText.includes('view')) continue;
        seen.add(m[1]);
        n++;
      }
      return n;
    })(),
    pagination: (() => {
      const pag = document.querySelector('.pagination');
      if (!pag) return { present: false };
      const items = Array.from(pag.querySelectorAll('li'));
      const pageNumbers = [];
      let activePage = null;
      let nextVisible = false;
      for (const li of items) {
        const text = (li.innerText || '').trim();
        const hidden = li.classList.contains('hidden');
        if (/^\\d+$/.test(text)) pageNumbers.push(Number(text));
        if (li.classList.contains('active')) activePage = text;
        if (/^next$/i.test(text) && !hidden) nextVisible = true;
      }
      const nextLi = items.find((li) => /^next$/i.test((li.innerText || '').trim()));
      return {
        present: true,
        itemCount: items.length,
        pageNumbers,
        activePage,
        totalPages: pageNumbers.length ? Math.max(...pageNumbers) : null,
        nextVisible,
        nextNgClick: nextLi ? (nextLi.getAttribute('ng-click') || '') : '',
        sampleItems: items.slice(0, 8).map((li) => ({
          text: (li.innerText || '').trim().slice(0, 40),
          hidden: li.classList.contains('hidden'),
          active: li.classList.contains('active'),
          ngClick: (li.getAttribute('ng-click') || '').slice(0, 80),
        })),
      };
    })(),
  };
}
"""


def main() -> None:
    if not os.path.isfile(AUTH):
        print("MISSING instahyre_auth.json — cannot probe live DOM")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=AUTH)
        page = context.new_page()
        page.goto(FEED_URL, timeout=90000, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        data = page.evaluate(PROBE_JS)
        print(json.dumps(data, indent=2))
        browser.close()


if __name__ == "__main__":
    main()

import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

// Wrap each word of a heading in a clipped mask so it can rise into view.
function splitWords(el) {
  if (el.dataset.splitDone) return [...el.querySelectorAll('.wi')];
  const text = el.textContent.trim().replace(/\s+/g, ' ');
  el.setAttribute('aria-label', text);
  el.textContent = '';
  text.split(' ').forEach((word, i, all) => {
    const mask = document.createElement('span');
    mask.className = 'w';
    mask.setAttribute('aria-hidden', 'true');
    const inner = document.createElement('span');
    inner.className = 'wi';
    inner.textContent = word;
    mask.append(inner);
    el.append(mask);
    if (i < all.length - 1) el.append(' ');
  });
  el.dataset.splitDone = '1';
  return [...el.querySelectorAll('.wi')];
}

const mm = gsap.matchMedia();

mm.add('(prefers-reduced-motion: no-preference)', () => {
  // Hero intro
  const hero = document.querySelector('[data-hero]');
  if (hero) {
    const h1 = hero.querySelector('h1');
    const words = h1 ? splitWords(h1) : [];
    const img = hero.querySelector('.bg');
    const tl = gsap.timeline({ defaults: { ease: 'power4.out' } });
    if (img) tl.from(img, { scale: 1.14, duration: 2.2, ease: 'power2.out' }, 0);
    if (words.length) tl.from(words, { yPercent: 115, duration: 1.1, stagger: 0.07 }, 0.15);
    tl.from(hero.querySelectorAll('[data-hero-in]'), { y: 28, opacity: 0, duration: 0.9, stagger: 0.1 }, 0.55);
    tl.from(hero.querySelectorAll('[data-hero-cell]'), { y: 40, opacity: 0, duration: 0.9, stagger: 0.12 }, 0.9);

    if (img) {
      gsap.to(img, { yPercent: 14, ease: 'none', scrollTrigger: { trigger: hero, start: 'top top', end: 'bottom top', scrub: true } });
    }
    const copy = hero.querySelector('[data-hero-copy]');
    if (copy) {
      gsap.to(copy, { yPercent: -10, opacity: 0.2, ease: 'none', scrollTrigger: { trigger: hero, start: '35% top', end: 'bottom top', scrub: true } });
    }
  }

  // Headlines: words rise out of a mask
  gsap.utils.toArray('[data-split]').forEach((el) => {
    if (hero && hero.contains(el)) return;
    const words = splitWords(el);
    gsap.from(words, {
      yPercent: 115, duration: 1, ease: 'power4.out', stagger: 0.06,
      scrollTrigger: { trigger: el, start: 'top 88%', once: true },
    });
  });

  // Generic fade-up reveal
  gsap.utils.toArray('[data-reveal]').forEach((el) => {
    gsap.from(el, {
      y: 36, opacity: 0, duration: 1, ease: 'power3.out', clearProps: 'transform,opacity',
      scrollTrigger: { trigger: el, start: 'top 90%', once: true },
    });
  });

  // Staggered children
  gsap.utils.toArray('[data-stagger]').forEach((group) => {
    gsap.from(group.children, {
      y: 30, opacity: 0, duration: 0.8, ease: 'power3.out', stagger: 0.07, clearProps: 'transform,opacity',
      scrollTrigger: { trigger: group, start: 'top 88%', once: true },
    });
  });

  // Image parallax inside an overflow-hidden frame
  gsap.utils.toArray('[data-parallax]').forEach((img) => {
    gsap.fromTo(img, { yPercent: -9, scale: 1.2 }, {
      yPercent: 9, scale: 1.2, ease: 'none',
      scrollTrigger: { trigger: img.parentElement, start: 'top bottom', end: 'bottom top', scrub: true },
    });
  });

  // Marquee speeds up with scroll velocity
  const marquee = document.querySelector('[data-marquee]');
  if (marquee) {
    const loop = gsap.to(marquee, { xPercent: -50, ease: 'none', duration: 38, repeat: -1 });
    ScrollTrigger.create({
      onUpdate: (self) => {
        const v = Math.min(Math.abs(self.getVelocity()) / 400, 5);
        gsap.to(loop, { timeScale: 1 + v, duration: 0.2, overwrite: true });
        gsap.to(loop, { timeScale: 1, duration: 1, delay: 0.2, overwrite: false });
      },
    });
  }
});

// Pinned horizontal scroll for the solutions section (desktop only)
mm.add('(min-width: 960px) and (prefers-reduced-motion: no-preference)', () => {
  const sec = document.querySelector('[data-hscroll]');
  const track = sec && sec.querySelector('[data-hscroll-track]');
  if (!sec || !track) return;
  sec.classList.add('is-pinned');
  const bar = sec.querySelector('[data-hscroll-bar]');
  const dist = () => Math.max(0, track.scrollWidth - sec.clientWidth);
  const tween = gsap.to(track, {
    x: () => -dist(),
    ease: 'none',
    scrollTrigger: {
      trigger: sec, pin: true, scrub: 0.7, start: 'top top',
      end: () => '+=' + dist(), invalidateOnRefresh: true, anticipatePin: 1,
      onUpdate: (self) => { if (bar) bar.style.transform = `scaleX(${self.progress})`; },
    },
  });
  // Panel images drift slightly against the track for depth
  gsap.utils.toArray('[data-hs-img]', sec).forEach((img) => {
    gsap.fromTo(img, { xPercent: -6 }, {
      xPercent: 6, ease: 'none',
      scrollTrigger: { trigger: img.closest('.panel'), containerAnimation: tween, start: 'left right', end: 'right left', scrub: true },
    });
  });
  return () => sec.classList.remove('is-pinned');
});

window.addEventListener('load', () => ScrollTrigger.refresh());

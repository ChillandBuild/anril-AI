"use client";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import s from "./LoginShowcase.module.css";

type Bubble = { channel: string; text: string; done: string; hot?: boolean };

const BUBBLES: Bubble[] = [
  {
    channel: "WhatsApp · Priya",
    text: "Fees evvalavu? Weekend batch irukka?",
    done: "Replied in 4s · Tanglish",
  },
  {
    channel: "Instagram · Arjun",
    text: "Is the 2BHK near OMR still available? Can I visit Sunday?",
    done: "Replied in 3s · visit booked",
    hot: true,
  },
  {
    channel: "Facebook · Meena",
    text: "நாளைக்கு appointment கிடைக்குமா?",
    done: "Replied in 5s · Tamil",
  },
  {
    channel: "WhatsApp · Karthik",
    text: "Price for 50 pieces, delivery to Madurai?",
    done: "Replied in 4s · quote sent",
  },
];

// Transparent video needs a different format per engine: Safari only does alpha
// in HEVC (.mov), everyone else in VP9 WebM, and Safari plays WebM but drops its
// alpha, so pick one rather than listing both as <source>s.
function isSafari() {
  return /^((?!chrome|chromium|crios|android|edg).)*safari/i.test(
    navigator.userAgent,
  );
}

// The login page's left side. Desktop only (the page mounts it at 1280px+, client
// side), so phones never download the videos.
//   peek:   Healy shuts its eyes (password field focused)
//   flying: Tealy flies off with the message (signing in)
//   width / height: layout size in px, before the page zooms it
//   over / overX: how far Healy and Tealy stick out past the corners
export default function LoginShowcase({
  width,
  height,
  over,
  overX,
  peek,
  flying,
}: {
  width: number;
  height: number;
  over: number;
  overX: number;
  peek: boolean;
  flying: boolean;
}) {
  const [still, setStill] = useState(false);
  const [ext] = useState(() => (isSafari() ? "mov" : "webm"));
  const type = ext === "mov" ? 'video/mp4; codecs="hvc1"' : "video/webm";
  const [lean, setLean] = useState({ x: 0, y: 0 });
  const tealyRef = useRef<HTMLVideoElement>(null);
  const healyRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setStill(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  // Some browsers ignore the autoplay attribute until muted is set as a property.
  useEffect(() => {
    if (still) return;
    for (const v of [tealyRef.current, healyRef.current]) {
      if (!v) continue;
      v.muted = true;
      v.play().catch(() => {});
    }
  }, [still]);

  useEffect(() => {
    if (still) return;
    let frame = 0;
    const onMove = (e: MouseEvent) => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setLean({
          x: (e.clientX / window.innerWidth) * 2 - 1,
          y: (e.clientY / window.innerHeight) * 2 - 1,
        });
      });
    };
    window.addEventListener("mousemove", onMove);
    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(frame);
    };
  }, [still]);

  const tealyLean = `translate(${lean.x * 18}px, ${lean.y * 12}px) rotate(${lean.x * 6}deg)`;
  const healyLean = `translate(${lean.x * 10}px, ${lean.y * 8}px) rotate(${lean.x * 4}deg)`;

  return (
    <div
      className={s.root}
      style={
        {
          width,
          height,
          "--over": `${over}px`,
          "--over-x": `${overX}px`,
          "--rise": `${height - 100}px`,
        } as React.CSSProperties
      }
    >
      <div className={`${s.blob} ${s.blobTeal}`} aria-hidden="true" />
      <div className={`${s.blob} ${s.blobCopper}`} aria-hidden="true" />

      <div className={s.glass}>
        <div className={s.copy}>
          <h2>Every lead, answered in seconds.</h2>
          <p>
            From &ldquo;Fees evvalavu?&rdquo; to a booked visit. anril AI
            handles the chat, you close the deal.
          </p>
          <div className={s.chips}>
            <span className={s.chip}>WhatsApp · Instagram · Facebook</span>
            <span className={s.chip}>Tamil · Tanglish · English</span>
            <span className={s.chip}>Hot-lead alerts</span>
          </div>
        </div>

        <div className={s.feed} aria-hidden="true">
          {BUBBLES.map((b, i) => (
            <div
              key={b.channel}
              className={s.bub}
              style={{ "--d": `${-4 * i}s` } as React.CSSProperties}
            >
              <div className={s.channel}>{b.channel}</div>
              <p>{b.text}</p>
              <div className={s.status}>
                <span className={s.typing}>
                  <span className={s.dots}>
                    <i />
                    <i />
                    <i />
                  </span>
                  Tealy is replying
                </span>
                <span className={s.done}>✓ {b.done}</span>
              </div>
              {b.hot && <span className={s.hot}>HOT LEAD</span>}
            </div>
          ))}
        </div>

        <div className={s.by}>
          A product from <b>Bloom Matrix</b>
        </div>
      </div>

      <span className={`${s.ping} ${s.pingReply}`} aria-hidden="true" />
      <span className={`${s.ping} ${s.pingLead}`} aria-hidden="true" />

      <div
        className={`${s.char} ${s.healy}`}
        style={{ transform: healyLean }}
        aria-hidden="true"
      >
        <div className={s.point}>
          <div className={`${s.media} ${peek ? s.shut : ""}`}>
            {still ? (
              <Image
                src="/login/healy-poster.png"
                alt=""
                width={480}
                height={480}
                priority
              />
            ) : (
              <video
                ref={healyRef}
                autoPlay
                loop
                muted
                playsInline
                poster="/login/healy-poster.png"
              >
                <source src={`/login/healy-alpha.${ext}`} type={type} />
              </video>
            )}
            <Image
              className={s.shutImg}
              src="/login/healy-shut.png"
              alt=""
              width={480}
              height={480}
            />
          </div>
        </div>
      </div>

      <div
        className={`${s.char} ${s.tealy}`}
        style={{ transform: tealyLean }}
        aria-hidden="true"
      >
        <div className={flying ? s.fly : s.deliver}>
          <div className={s.media}>
            {still ? (
              <Image
                src="/login/tealy-poster.png"
                alt=""
                width={480}
                height={480}
                priority
              />
            ) : (
              <video
                ref={tealyRef}
                autoPlay
                loop
                muted
                playsInline
                poster="/login/tealy-poster.png"
              >
                <source src={`/login/tealy-alpha.${ext}`} type={type} />
              </video>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

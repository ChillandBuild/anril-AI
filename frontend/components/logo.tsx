import { SVGProps } from "react";

// Anril AI logo: the four-square mark + the "anril AI" wordmark.
// Wordmark is Outfit Bold (700) converted to paths, so it renders identically
// everywhere without loading the font. Letters and the three plain squares
// follow currentColor (navy via text-ink, white via text-white); the mark's
// top-right square, the i-dot and "AI" are always teal #038285.
const TEAL = "#038285";
const VIEW_BOX = { x: -948, y: -726, width: 4140, height: 736 };
const ASPECT = VIEW_BOX.width / VIEW_BOX.height;
// The 200-unit mark scaled to the wordmark's height, placed left of it.
const MARK_TRANSFORM = `translate(${VIEW_BOX.x} ${VIEW_BOX.y}) scale(3.68)`;

const LETTERS =
  "M257 10Q190 10 137.25 -23.0Q84.5 -56.0 54.25 -113.0Q24 -170 24.0 -242.5Q24.0 -315.5 54.25 -372.75Q84.5 -430.0 137.25 -463.0Q190 -496 257 -496Q306 -496 345.5 -477.0Q385 -458 409.75 -424.5Q434.5 -391.0 438 -348V-138Q434.5 -95.0 410.0 -61.5Q385.5 -28.0 345.75 -9.0Q306 10 257 10ZM288 -128Q337 -128 367.0 -160.25Q397.0 -192.5 397 -243Q397 -277 383.5 -302.75Q370.0 -328.5 345.5 -343.25Q321 -358 288.5 -358.0Q256.5 -358.0 232.0 -343.25Q207.5 -328.5 193.25 -302.5Q179.0 -276.5 179 -243Q179.0 -209.5 193.0 -183.5Q207.0 -157.5 231.75 -142.75Q256.5 -128.0 288 -128ZM390.5 0.0V-130.5L413.5 -249.0L390.5 -366.5V-486.0H541V0Z M970 0V-276.5Q970 -315 946.5 -338.25Q923.0 -361.5 886.6224489795918 -361.5Q861.8724489795918 -361.5 842.6862244897959 -351.0Q823.5 -340.5 812.75 -321.25Q802 -302 802.0 -276.5L742.5 -305.5Q742.5 -363.0 767.75 -405.75Q793.0 -448.5 837.4479695431472 -472.25Q881.8959390862944 -496.0 938.1979695431472 -496.0Q991.5 -496.0 1033.25 -470.5Q1075 -445 1099.0 -403.0Q1123 -361 1123 -311V0ZM649 0V-486H802V0Z M1221 0V-486H1374V0ZM1374.0 -266.5 1309.5 -316.5Q1328.5 -402.0 1373.9969325153374 -449.0Q1419.493865030675 -496.0 1498.5 -496.0Q1533.5 -496.0 1560.25 -485.5Q1587 -475 1607 -453L1516 -338Q1506 -349 1491.1944444444443 -354.75Q1476.388888888889 -360.5 1457.0 -360.5Q1419.0 -360.5 1396.5 -337.125786163522Q1374.0 -313.751572327044 1374.0 -266.5Z M1665 0V-486H1818V0Z M1926 0V-726H2079V0Z";
const I_DOT =
  "M1741.5 -553.0Q1706 -553 1682.5 -577.25Q1659.0 -601.5 1659 -637Q1659.0 -672.5 1682.5 -696.75Q1706 -721 1741.5 -721.0Q1778 -721 1801.0 -696.75Q1824.0 -672.5 1824 -637Q1824.0 -601.5 1801.0 -577.25Q1778 -553 1741.5 -553.0Z";
const AI =
  "M2252.5 0 2532.0 -706.0H2674.0L2951.0 0.0H2785.0L2573.5 -586H2630.5L2415.5 0ZM2411.5 -127.5V-255.5H2796.0V-127.5Z M3034.0 0.0V-706.0H3191.5V0Z";

// 2x2 grid of 95-unit rounded squares on a 200-unit grid; [x, y, isAccent].
const SQUARES: ReadonlyArray<readonly [number, number, boolean]> = [
  [0, 0, false],
  [105, 0, true],
  [0, 105, false],
  [105, 105, false],
];

function MarkSquares() {
  return (
    <>
      {SQUARES.map(([x, y, isAccent]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="95" height="95" rx="26" fill={isAccent ? TEAL : "currentColor"} />
      ))}
    </>
  );
}

type LogoProps = SVGProps<SVGSVGElement>;

export function AnrilLogo({ width, height = 36, ...rest }: LogoProps) {
  const calculatedWidth = width ?? (typeof height === "number" ? Math.round(height * ASPECT) : undefined);

  return (
    <svg
      width={calculatedWidth}
      height={height}
      viewBox={`${VIEW_BOX.x} ${VIEW_BOX.y} ${VIEW_BOX.width} ${VIEW_BOX.height}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Anril AI"
      {...rest}
    >
      <g transform={MARK_TRANSFORM}>
        <MarkSquares />
      </g>
      <path d={LETTERS} fill="currentColor" />
      <path d={I_DOT} fill={TEAL} />
      <path d={AI} fill={TEAL} />
    </svg>
  );
}

/** The "anril AI" letters alone (no mark), for light surfaces such as the app header. */
export function AnrilWordmark({ height = 20, ...rest }: LogoProps) {
  return (
    <svg
      height={height}
      viewBox="0 -726 3192 736"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Anril AI"
      {...rest}
    >
      <path d={LETTERS} fill="currentColor" />
      <path d={I_DOT} fill={TEAL} />
      <path d={AI} fill={TEAL} />
    </svg>
  );
}

/**
 * The mark's four squares laid in one row: three plain (currentColor) and the
 * teal one last. Each square is a <rect> so CSS can animate them one by one.
 */
export function AnrilMarkRow({ height = 18, accent = TEAL, ...rest }: LogoProps & { accent?: string }) {
  return (
    <svg
      height={height}
      viewBox="0 0 410 95"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Anril AI"
      {...rest}
    >
      {[0, 105, 210, 315].map((x) => (
        <rect key={x} x={x} width="95" height="95" rx="26" fill={x === 315 ? accent : "currentColor"} />
      ))}
    </svg>
  );
}

/** The four-square mark alone, for tight spots such as the collapsed sidebar. */
export function AnrilMark({ width = 32, height = 32, ...rest }: LogoProps) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 200 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Anril AI"
      {...rest}
    >
      <MarkSquares />
    </svg>
  );
}

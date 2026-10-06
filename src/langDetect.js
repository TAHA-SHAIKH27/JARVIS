// langDetect.js — frontend mirror of backend/agent/lang_detect.py (same rules).
// Detects hi/mr/ur/en/fr/es for a reply and picks a matching browser voice
// so JARVIS speaks Hindi, Urdu, Marathi, French, Spanish — not just English.

const MR_MARKERS = ['आहे', 'नाही', 'नको', 'मला', 'तुला', 'तुम्ही', 'आम्ही',
  'कसे', 'कशी', 'कुठे', 'माझा', 'माझं', 'माझी', 'होय', 'पाहिजे', 'करतो', 'करते'];
const HI_MARKERS = ['है', 'हैं', 'नहीं', 'मुझे', 'तुम्हें', 'कैसे', 'कहाँ',
  'क्या', 'मेरा', 'मेरी', 'आपका', 'होगा', 'रहा', 'रही', 'वाला'];

const HINTS = [
  ['hi', ['in hindi', 'hindi me', 'hindi mein', 'हिंदी में', 'हिन्दी में', 'hindi joke', 'hindi story']],
  ['mr', ['in marathi', 'marathi me', 'marathi madhe', 'मराठीत', 'मराठी मध्ये', 'marathi joke', 'marathi story']],
  ['ur', ['in urdu', 'urdu me', 'urdu mein', 'اردو میں', 'urdu joke', 'urdu story']],
  ['fr', ['in french', 'en français', 'en francais', 'french joke', 'french story']],
  ['es', ['in spanish', 'en español', 'en espanol', 'spanish joke', 'spanish story']],
  ['en', ['in english', 'english joke']],
];

export function detectLang(text, hint = '') {
  try {
    const loweredHint = (hint || '').toLowerCase();
    for (const [lang, patterns] of HINTS) {
      if (patterns.some(p => loweredHint.includes(p))) return lang;
    }
    const t = text || '';
    if (/[ऀ-ॿ]/.test(t)) {
      const mr = MR_MARKERS.filter(m => t.includes(m)).length;
      const hi = HI_MARKERS.filter(m => t.includes(m)).length;
      return mr > hi ? 'mr' : 'hi';
    }
    if (/[؀-ۿ]/.test(t)) return 'ur';
    if (/[ñ¿¡]/.test(t)) return 'es';
    if (/[çœæàâêëîïôûù]/.test(t)) return 'fr';
  } catch { /* fall through */ }
  return 'en';
}

// BCP-47 tags to try in order. Marathi falls back to a Hindi voice (same
// script family) when no Marathi voice is installed — far closer than English.
const LANG_TAGS = {
  hi: ['hi-IN', 'hi'],
  mr: ['mr-IN', 'mr', 'hi-IN', 'hi'],
  ur: ['ur-PK', 'ur-IN', 'ur'],
  en: ['en-IN', 'en-US', 'en-GB', 'en'],
  fr: ['fr-FR', 'fr'],
  es: ['es-ES', 'es-US', 'es'],
};

const LANG_NAMES = {
  hi: ['hindi'], mr: ['marathi'], ur: ['urdu'],
  en: ['english'], fr: ['french', 'français'], es: ['spanish', 'español'],
};

let cachedVoices = [];
function refreshVoices() {
  try {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      const v = window.speechSynthesis.getVoices();
      if (v && v.length) cachedVoices = v;
    }
  } catch { /* ignore */ }
  return cachedVoices;
}
if (typeof window !== 'undefined' && window.speechSynthesis) {
  refreshVoices();
  try {
    window.speechSynthesis.onvoiceschanged = refreshVoices;
  } catch { /* ignore */ }
}

// Voices that speak English with a non-native accent (installed with East
// Asian language packs). They must never be chosen for English — a previous
// bug let one through when the voice list hadn't finished loading.
const CJK_LANG_PREFIXES = ['zh', 'ja', 'ko'];
const CJK_NAME_TOKENS = new Set([
  'huihui', 'yaoyao', 'kangkang', 'yunjian', 'xiaoxiao', 'xiaomo',
  'xiaoyi', 'haruka', 'ichiro', 'ayumi', 'sayaka', 'naoya', 'nanami',
  'jiajia', 'meimei', 'liang', 'keita', 'nozomi',
]);
function isCJKVoice(v) {
  const lang = (v.lang || '').toLowerCase();
  if (CJK_LANG_PREFIXES.some((p) => lang === p || lang.startsWith(p + '-'))) return true;
  const tokens = `${v.name || ''}`.toLowerCase().split(/[^a-z]+/);
  return tokens.some((t) => CJK_NAME_TOKENS.has(t));
}

// Native English male voices, best first. Checked by name before any
// locale matching so JARVIS always sounds like a native speaker.
const PREFERRED_NATIVE_EN = [
  'microsoft david', 'google uk english male', 'microsoft mark',
  'microsoft george', 'microsoft daniel', 'google us english', 'daniel',
];

// JARVIS is male, so within any language tier a male voice always wins.
// Browser voices rarely expose gender directly — detect it from the voice
// name (e.g. "Microsoft David" male vs "Microsoft Zira" female, "Google UK
// English Male"). Tokens are matched whole-word so "man" never matches
// "Samantha".
const MALE_TOKENS = new Set([
  'male', 'man', 'david', 'mark', 'daniel', 'james', 'george', 'guy',
  'madhur', 'hemant', 'pablo', 'jorge', 'diego', 'carlos', 'paul',
  'thomas', 'alexander', 'fred', 'daniel', 'arthur', 'oscar',
]);
const FEMALE_TOKENS = new Set([
  'female', 'woman', 'zira', 'samantha', 'aria', 'jenny', 'swara',
  'kalpana', 'helena', 'laura', 'monica', 'hortense', 'julie', 'hazel',
  'sabina', 'heera', 'kanya', 'veena', 'lekha', 'susan', 'karen',
]);

export function voiceGender(name) {
  const tokens = `${name || ''}`.toLowerCase().split(/[^a-zàâêëîïôûùçœæñ]+/);
  let male = false, female = false;
  for (const t of tokens) {
    if (MALE_TOKENS.has(t)) male = true;
    if (FEMALE_TOKENS.has(t)) female = true;
  }
  if (male && !female) return 'male';
  if (female && !male) return 'female';
  return 'unknown';
}

// Male voices first, then gender-unknown (e.g. "Google US English"), with
// female voices strictly last — JARVIS must never sound female when a male
// (or neutral) alternative exists in the same language.
function preferMaleFirst(voices) {
  const rank = (v) => {
    const g = voiceGender(v.name);
    return g === 'male' ? 0 : g === 'unknown' ? 1 : 2;
  };
  return [...voices].sort((a, b) => rank(a) - rank(b));
}

export function pickBrowserVoice(lang) {
  // The voice list loads asynchronously — re-read it live so we never
  // speak with the browser default (often a non-native voice) just
  // because the cache was still empty.
  if (!cachedVoices.length) refreshVoices();
  // CJK voices are never eligible for any language JARVIS speaks.
  const pool = cachedVoices.filter((v) => !isCJKVoice(v));
  if (!pool.length) return null;
  if (lang === 'en' || !lang) {
    const lowered = pool.map((v) => `${v.name || ''}`.toLowerCase());
    for (const pref of PREFERRED_NATIVE_EN) {
      const i = lowered.findIndex((n) => n.includes(pref));
      if (i >= 0) return pool[i];
    }
  }
  const tags = LANG_TAGS[lang] || LANG_TAGS.en;
  for (const tag of tags) {
    const matches = pool.filter(
      (x) => (x.lang || '').toLowerCase() === tag.toLowerCase()
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  for (const tag of tags) {
    const short = tag.split('-')[0];
    const matches = pool.filter(
      (x) => (x.lang || '').toLowerCase().startsWith(short)
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  const names = LANG_NAMES[lang] || [];
  for (const n of names) {
    const matches = pool.filter(
      (x) => `${x.name || ''}`.toLowerCase().includes(n)
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  // No voice for this language at all: fall back to any male/neutral
  // English voice rather than an arbitrary (often female) default.
  const enFallback = preferMaleFirst(
    pool.filter((x) => (x.lang || '').toLowerCase().startsWith('en'))
  );
  if (enFallback.length) return enFallback[0];
  const anyMale = preferMaleFirst(pool);
  return anyMale.length ? anyMale[0] : null;
}

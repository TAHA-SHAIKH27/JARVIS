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
if (typeof window !== 'undefined' && window.speechSynthesis) {
  const refresh = () => {
    try {
      const v = window.speechSynthesis.getVoices();
      if (v && v.length) cachedVoices = v;
    } catch { /* ignore */ }
  };
  refresh();
  try {
    window.speechSynthesis.onvoiceschanged = refresh;
  } catch { /* ignore */ }
}

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

function voiceGender(name) {
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
  const tags = LANG_TAGS[lang] || LANG_TAGS.en;
  for (const tag of tags) {
    const matches = cachedVoices.filter(
      (x) => (x.lang || '').toLowerCase() === tag.toLowerCase()
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  for (const tag of tags) {
    const short = tag.split('-')[0];
    const matches = cachedVoices.filter(
      (x) => (x.lang || '').toLowerCase().startsWith(short)
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  const names = LANG_NAMES[lang] || [];
  for (const n of names) {
    const matches = cachedVoices.filter(
      (x) => `${x.name || ''}`.toLowerCase().includes(n)
    );
    if (matches.length) return preferMaleFirst(matches)[0];
  }
  // No voice for this language at all: fall back to any male/neutral
  // English voice rather than an arbitrary (often female) default.
  const enFallback = preferMaleFirst(
    cachedVoices.filter((x) => (x.lang || '').toLowerCase().startsWith('en'))
  );
  if (enFallback.length) return enFallback[0];
  const anyMale = preferMaleFirst(cachedVoices);
  return anyMale.length ? anyMale[0] : null;
}

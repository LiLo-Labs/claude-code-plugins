export const meta = {
  name: 'visual-paint',
  description: 'Visual agents identify a model, enumerate its features, select them, propose colour plans and critique the renders',
  whenToUse: 'Painting any 3D model where the features must be found by looking rather than by threshold',
  phases: [
    { title: 'Identify', detail: 'what is this object, and what vocabulary describes its parts' },
    { title: 'Survey', detail: 'generic lenses enumerate every visible feature with pixel coordinates' },
    { title: 'Select', detail: 'observations become verified triangle selections' },
    { title: 'Colour', detail: 'plans proposed against the confirmed parts' },
    { title: 'Critique', detail: 'visual critics judge the renders' },
  ],
}

// Everything model-specific arrives in args. Nothing in this file knows or
// assumes what the model depicts: the vocabulary for its parts is derived by the
// Identify phase and passed forward, so the same script serves a creature, a
// terrain piece, a vehicle or a bracket.
const config = args || {}
const PLUGIN = config.plugin || '/home/user/claude-code-plugins/plugins/model-paint'
const WORK = config.session
const VIEWS = config.views || ['front', 'back', 'left', 'right', 'top', 'iso', 'iso2']
const FILAMENTS = config.filaments || []
const STYLE_COUNT = Math.max(1, Math.min(4, config.styles || 3))

if (!WORK) throw new Error('args.session is required (directory from inspect_model.py)')

const palette = FILAMENTS.map((f) => `  ${f.index} ${f.name} ${f.hex}`).join('\n')

const CONTEXT = `
THE JOB
Paint one 3D model for multi-filament printing. Features must be found by LOOKING
at it, because no threshold generalises across models: the same settings that
separate a creature's horns leave a sculpted terrain piece as one undifferentiated
region. Your eyes are the primary instrument. The geometry tools below are
instruments you reach for once you have decided what you are looking at.

YOUR EYES
Ray-traced views, ${VIEWS.length} of them, at ${WORK}/views/
  ${VIEWS.map((v) => v + '.png').join(' ')}
READ THEM with the Read tool. Pixel (0,0) is top-left. Each view carries a pick map,
so any pixel coordinate you cite can be resolved to actual triangles.

THE FILAMENTS (independent nozzles: no swaps, no purge tower, so this set is fixed)
${palette || '  (none supplied)'}

RULES
- Geometry is never modified. You select and you colour. Nothing else.
- Never edit anything under ${PLUGIN}/scripts, and never write into ${WORK}/session.npz
  or ${WORK}/views.
- Work only inside the directory your task names.
- Deterministic output: no timestamps, no random seeds, no wall-clock values.
`

const TOOLS = `
TOOLS

Select what you can see:
  python3 ${PLUGIN}/scripts/select_region.py --session <dir> --at <view>:<x>,<y> \\
      --grow <rough|thin|cavity|smooth|patch> --name "<what it is>"
  Repeat --at to fold several seeds into one part. Add --replace to redo a part.
  It prints the triangle count and area share, and writes a highlight render to
  <dir>/selections/<slug>-<view>.png.
  ALWAYS Read that highlight. Does the red cover what you pointed at, and nothing
  else? Too much: lower --tolerance. Too little: raise it, or change --grow. If it
  exceeded the size cap it refuses rather than swallowing the model.

  Choosing --grow is a judgement about what the thing IS:
    rough   spread while the surface stays bumpy   (granular or encrusted texture)
    thin    spread while the solid stays thin      (anything standing off the form)
    cavity  spread while the surface stays recessed (openings, channels, hollows)
    smooth  spread while the surface stays flat     (panels, plates, broad faces)
    patch   spread until a crease stops it          (anything with a hard edge)

Render a colour plan:
  python3 ${PLUGIN}/scripts/render_plan.py --features <session.npz> \\
      --parts <parts.json> --plan <plan.json> --output <dir>
  Plan shape, addressed by the part NAMES you chose:
    {"default": "#RRGGBB",
     "parts": {"<part name>": {"outside": "#RRGGBB", "inside": "#RRGGBB", "cut": 0.6}},
     "views": ["front","iso"],
     "crops": [{"name":"detail","centre":[x,y,z],"radius":12}]}
  "inside" repaints the recessed share of a part, selected by occlusion above "cut"
  (0..1, higher is deeper). Recesses read as shadow, so inside is normally the
  darker filament. This is how an opening gets a dark interior without spending a
  second filament on it, and it is the main thing separating a painted model from a
  colouring-book fill.
`

const IDENTITY = {
  type: 'object',
  additionalProperties: false,
  required: ['subject', 'category', 'vocabulary', 'dominant_form', 'confidence'],
  properties: {
    subject: { type: 'string', description: 'what this object actually is, in a sentence' },
    category: { type: 'string', enum: ['creature', 'figure', 'terrain', 'vehicle', 'mechanical', 'architectural', 'decorative', 'abstract', 'other'] },
    vocabulary: {
      type: 'array',
      items: { type: 'string' },
      description: 'the words a person would use for this object’s parts, derived from what you see, not from a fixed list',
    },
    dominant_form: { type: 'string', description: 'the mass carrying most of the surface area' },
    has_base: { type: 'boolean', description: 'whether it sits on ground, a plinth or a stand' },
    symmetry: { type: 'string', description: 'mirror, radial, none, and about which axis' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    uncertain_regions: { type: 'array', items: { type: 'string' }, description: 'anything you cannot identify from the views' },
  },
}

const SURVEY = {
  type: 'object',
  additionalProperties: false,
  required: ['features', 'notes'],
  properties: {
    features: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'what_it_is', 'seeds', 'suggested_grow', 'confidence'],
        properties: {
          name: { type: 'string' },
          what_it_is: { type: 'string', description: 'what you believe it is, and what in the image tells you' },
          seeds: { type: 'array', items: { type: 'string' }, description: 'view:x,y, one or more' },
          suggested_grow: { type: 'string', enum: ['rough', 'thin', 'cavity', 'smooth', 'patch'] },
          approx_count: { type: 'integer', description: 'instances of this kind visible on the whole model' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
      },
    },
    notes: { type: 'string', description: 'ambiguities, and what you could not identify' },
  },
}

const SELECTION = {
  type: 'object',
  additionalProperties: false,
  required: ['parts', 'rejected', 'parts_file'],
  properties: {
    parts_file: { type: 'string' },
    parts: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'faces', 'area', 'grow', 'verified'],
        properties: {
          name: { type: 'string' },
          faces: { type: 'integer' },
          area: { type: 'number' },
          grow: { type: 'string' },
          tolerance: { type: 'number' },
          verified: { type: 'string', description: 'what the highlight render actually showed' },
        },
      },
    },
    rejected: { type: 'array', items: { type: 'string' } },
  },
}

const CRITIQUE = {
  type: 'object',
  additionalProperties: false,
  required: ['verdict', 'score', 'strengths', 'problems', 'specific_changes'],
  properties: {
    verdict: { type: 'string', enum: ['ship', 'revise', 'reject'] },
    score: { type: 'integer', description: '0-100 as a painted print' },
    strengths: { type: 'array', items: { type: 'string' } },
    problems: { type: 'array', items: { type: 'string' }, description: 'visible in the render, and described' },
    specific_changes: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['part', 'change', 'why'],
        properties: {
          part: { type: 'string' },
          change: { type: 'string', description: 'concrete: which filament, which cut value' },
          why: { type: 'string' },
        },
      },
    },
  },
}

// Lenses are structural, not subject-specific. Every model has a dominant form;
// most have protrusions, applied surface detail and recesses; some have a base.
// A lens that finds nothing says so, which is information rather than failure.
const LENSES = [
  {
    key: 'primary-form',
    lens: `THE DOMINANT FORM. The one or few masses carrying most of the surface area, and
the large-scale divisions within them: panels, plates, broad faces, growth bands,
major sections. This is the part that will take the base colour, so its extent
matters more than its detail. Ignore anything small or attached.`,
  },
  {
    key: 'protrusions',
    lens: `THINGS STANDING OFF THE FORM. Anything projecting outward: limbs, spikes, horns,
tubes, fins, handles, brackets, spines, antennae. Note for each whether it stands
clear or merges smoothly into what it grows from, because that decides whether it
can be selected at all.`,
  },
  {
    key: 'surface-detail',
    lens: `APPLIED SURFACE DETAIL. Whatever sits ON a surface rather than being part of its
shape: repeated texture, granular or encrusted patches, scales, rivets, studs,
inscriptions, patterning, damage, wear. These are usually small, often repeated,
and easy to miss. Sweep every view and give a separate seed for each distinct
patch and each isolated instance, not only the largest ones.`,
  },
  {
    key: 'recesses',
    lens: `NEGATIVE SPACE. Openings, cavities, hollows, channels, deep seams, undercuts,
sockets, anything you look INTO rather than at. These drive the inside/outside
split that gives a painted model depth, so locating them well is worth more than
locating one more bump.`,
  },
  {
    key: 'support',
    lens: `WHAT IT STANDS ON. A base, plinth, ground, stand, or integrated terrain, and the
join where the object meets it. Many models have none: if this one does not, say
so plainly and do not invent one.`,
  },
  {
    key: 'sweep',
    lens: `WHAT THE OTHERS WILL MISS. Do not catalogue the obvious. Look for detail visible
in only one view, small isolated features, undersides of overhangs, anything whose
identity is genuinely ambiguous, and any sizeable region nobody would have named.
Your value is entirely in what a first pass would skip.`,
  },
]

phase('Identify')

const identity = await agent(
  `${CONTEXT}\n\nTASK: identify this object before anything is measured or selected.\n` +
  `Read every view. Say what it is, what category it falls into, and what words a\n` +
  `person would use for its parts. That vocabulary is derived from what you see --\n` +
  `do not borrow a checklist from some other kind of model, and do not force\n` +
  `anatomy onto an object that has none.\n` +
  `Name the mass that carries most of the surface, whether it stands on anything,\n` +
  `and what symmetry it has. Be honest in uncertain_regions about what you cannot\n` +
  `make out; a later pass can look closer.`,
  { label: 'identify', phase: 'Identify', schema: IDENTITY, effort: 'high' })

if (!identity) throw new Error('identification failed; cannot proceed without it')
log(`subject: ${identity.subject} (${identity.category}, ${identity.confidence} confidence)`)
log(`vocabulary: ${(identity.vocabulary || []).join(', ')}`)

const SUBJECT = `
WHAT THIS MODEL IS (established by an earlier pass, from the same views)
  subject:       ${identity.subject}
  category:      ${identity.category}
  dominant form: ${identity.dominant_form}
  base:          ${identity.has_base ? 'yes' : 'no'}
  symmetry:      ${identity.symmetry}
  vocabulary:    ${(identity.vocabulary || []).join(', ')}
  unresolved:    ${(identity.uncertain_regions || []).join('; ') || 'none noted'}
Use that vocabulary when naming what you find. Disagree with it if the views say
otherwise -- it is a prior, not an instruction.
`

phase('Survey')

const surveys = await parallel(LENSES.map((lens) => () =>
  agent(
    `${CONTEXT}\n${SUBJECT}\n\nYOUR LENS\n${lens.lens}\n\n` +
    `TASK: enumerate what you see through your lens.\n` +
    `For each feature: a short name, what you think it is and what in the image tells\n` +
    `you so, one or more view:x,y seeds pointing at it, and the --grow strategy that\n` +
    `suits it. Read every view before answering; a feature invisible from the front is\n` +
    `often obvious from the back or top. Run no selections yet.\n` +
    `Pixel coordinates will be used literally, so be precise. If your lens finds\n` +
    `nothing on this model, return an empty list and say why in notes.`,
    { label: `survey:${lens.key}`, phase: 'Survey', schema: SURVEY, effort: 'high' })
))

const found = surveys.filter(Boolean)
const candidates = found.flatMap((s, i) => (s.features || []).map((f) => ({ ...f, lens: LENSES[i].key })))
log(`${candidates.length} candidate features from ${found.length} lenses`)

phase('Select')

// Selection work is split by lens so that agents never contend for the same
// parts.json, and so the split stays meaningful on any model rather than keying
// on words that only make sense for one subject.
const BUCKETS = [
  { dir: 'select-a', lenses: ['primary-form', 'recesses'] },
  { dir: 'select-b', lenses: ['surface-detail', 'sweep'] },
  { dir: 'select-c', lenses: ['protrusions', 'support'] },
]

const selections = await parallel(BUCKETS.map((bucket) => () => {
  const todo = candidates.filter((f) => bucket.lenses.includes(f.lens))
  if (!todo.length) return Promise.resolve(null)
  return agent(
    `${CONTEXT}\n${SUBJECT}\n${TOOLS}\n\n` +
    `TASK: turn these observations into verified selections.\n` +
    `Your working directory is ${WORK}/${bucket.dir} -- pass it as --session. It has\n` +
    `the shared session and views linked in; your parts.json lands there.\n\n` +
    `FEATURES (another agent's observations: a starting point, not gospel):\n` +
    JSON.stringify(todo, null, 2) + `\n\n` +
    `For each: run select_region.py, then READ the highlight it writes and judge it\n` +
    `honestly. Does the red cover the feature and stop where the feature stops? Adjust\n` +
    `--tolerance or --grow and re-run with --replace until it is right, or abandon that\n` +
    `feature and record why in "rejected". A selection you did not look at is not\n` +
    `verified, and the "verified" field must describe what the image actually showed.\n\n` +
    `Merge duplicates that turn out to be the same region. Keep names descriptive and\n` +
    `in the vocabulary above: they are what the user reads and what the colour plan\n` +
    `addresses.`,
    { label: `select:${bucket.dir}`, phase: 'Select', schema: SELECTION, effort: 'high' })
}))

const verified = selections.filter(Boolean)
const partCount = verified.reduce((n, s) => n + (s.parts?.length || 0), 0)
log(`${partCount} verified parts across ${verified.length} buckets`)

phase('Colour')

// Style briefs describe an intent, not a subject. "Materials read true" means
// something on a bracket as much as on a creature.
const STYLES = [
  { key: 'natural', brief: `Materials read true. Whatever this object is made of, the colour should say so, and the eye should accept it before it admires it. Earn chroma; do not spend it for its own sake.` },
  { key: 'tabletop', brief: `Painted to be seen from a metre away in ordinary room light. Every part you bothered to select must still read at that distance. Contrast beats subtlety, and depth in the recesses is what sells it.` },
  { key: 'bold', brief: `The most colour these filaments can carry without the object becoming a toy. Put chroma on a part large enough to register, and let the neutrals do the structural work.` },
].slice(0, STYLE_COUNT)

const CRITIC_LENSES = [
  { key: 'material', brief: `Does this read as a real object of its kind? Do the materials make sense together? Call out anything that looks like a fill rather than a painted model.` },
  { key: 'legibility', brief: `Imagine it printed at its real size and sitting a metre away under ordinary light. Which features still read, and which vanish into their surroundings? A small part that disappears is a failure even when the colours are pleasant. Filament prints flatter than a screen render, and recesses go darker than they look here.` },
  { key: 'harmony', brief: `Judge it purely as colour: balance, where the eye lands first and whether it should, whether the palette holds together or fights itself, and whether the chroma is spent in the right place given how few filaments there are.` },
]

const plans = await pipeline(
  STYLES,
  (style) => agent(
    `${CONTEXT}\n${SUBJECT}\n${TOOLS}\n\n` +
    `TASK: propose a colour plan in the "${style.key}" style.\n${style.brief}\n\n` +
    `VERIFIED PARTS, with triangle counts and area shares:\n` +
    JSON.stringify(verified, null, 2) + `\n\n` +
    `Address parts by name. Merge the bucket parts.json files into one file at\n` +
    `${WORK}/parts-${style.key}.json (concatenate their "parts" arrays; if two parts\n` +
    `overlap heavily, keep the better one and say which you dropped).\n` +
    `Write your plan to ${WORK}/plan-${style.key}.json and render it:\n` +
    `  python3 ${PLUGIN}/scripts/render_plan.py --features ${WORK}/session.npz \\\n` +
    `      --parts ${WORK}/parts-${style.key}.json --plan ${WORK}/plan-${style.key}.json \\\n` +
    `      --output ${WORK}/render-${style.key}\n` +
    `Use at least two views plus one crop tight on the finest detail you selected, so\n` +
    `the small work is judgeable.\n\n` +
    `Then READ your own render and revise at least once. What you imagined and what\n` +
    `the renderer produced are never the same thing. Use inside/cut on the parts that\n` +
    `deserve it -- a flat colour per part is exactly what this pipeline exists to get\n` +
    `past. Assign the largest part to the filament you would set as the object default,\n` +
    `and say which that is.\n\n` +
    `Return the plan path, the default filament, and an honest description of what the\n` +
    `render actually looks like -- including anything that came out worse than intended.`,
    { label: `plan:${style.key}`, phase: 'Colour', effort: 'high' }),
  (result, style) => {
    if (!result) return null
    return parallel(CRITIC_LENSES.map((critic) => () =>
      agent(
        `${CONTEXT}\n${SUBJECT}\n\n` +
        `TASK: critique a painted render through the "${critic.key}" lens.\n${critic.brief}\n\n` +
        `Render:  ${WORK}/render-${style.key}/plan.png  -- Read it.\n` +
        `Plan:    ${WORK}/plan-${style.key}.json        -- read it so you know the intent.\n` +
        `The author's own account: ${String(result).slice(0, 1500)}\n\n` +
        `Be a hard marker. "Looks good" is worthless. Every problem must be something\n` +
        `you can see in the image and describe in words, and every suggested change must\n` +
        `name the part, the filament, and the cut value where one applies. If it is\n` +
        `genuinely good, say so and score it high -- but justify that from the image too.`,
        { label: `critique:${style.key}:${critic.key}`, phase: 'Critique', schema: CRITIQUE, effort: 'high' })
    )).then((verdicts) => ({ style: style.key, plan: result, verdicts: verdicts.filter(Boolean) }))
  }
)

const judged = plans.filter(Boolean)
for (const entry of judged) {
  const scores = entry.verdicts.map((v) => v.score)
  const mean = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0
  log(`${entry.style}: mean ${mean} (${scores.join(', ')})`)
}

return {
  identity,
  survey: { lenses: found.length, candidates: candidates.length, notes: found.map((s) => s.notes) },
  selected: verified,
  plans: judged.map((entry) => ({
    style: entry.style,
    render: `${WORK}/render-${entry.style}/plan.png`,
    plan_file: `${WORK}/plan-${entry.style}.json`,
    parts_file: `${WORK}/parts-${entry.style}.json`,
    mean_score: entry.verdicts.length
      ? Math.round(entry.verdicts.reduce((a, v) => a + v.score, 0) / entry.verdicts.length)
      : null,
    verdicts: entry.verdicts,
  })),
}

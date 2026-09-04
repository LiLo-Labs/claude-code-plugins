#!/usr/bin/env python3
"""Game-asset concept graph.

  T[name] = (is_a_parent, [match terms], [has_parts], domain)

`domain` gates matching by file type and is the fix for cross-domain homonyms:
"hammer" in a .ncw sample is a piano hammer, not a weapon, so weapon concepts are
gated to visual/model files and instrument concepts to audio.

  visual  png jpg jpeg gif bmp tga webp psd svg aseprite
  model   fbx obj gltf glb dae blend stl mtl
  audio   wav mp3 ogg flac aiff ncw nki
  any     applies regardless

Terms are mined from this library's own 814k filenames, not invented.
"""
V, M, A, X = "visual", "model", "audio", "any"
VM = "visual|model"

T = {
 # ═══ roots ══════════════════════════════════════════════════════════════
 "object":(None,[],[],X), "creature":(None,[],[],X), "environment":(None,[],[],X),
 "effect":(None,[],[],X), "interface":(None,[],[],V), "sound":(None,[],[],A),
 "surface":(None,[],[],X), "style":(None,[],[],X), "attribute":(None,[],[],X),
 "setting":(None,[],[],X), "format":(None,[],[],X),

 # ═══ wearables ══════════════════════════════════════════════════════════
 "wearable":("object",["equip","equipment","outfit","garment","wearable"],[],VM),
 "clothing":("wearable",["clothing","clothes","apparel","costume"],[],VM),
 "shirt":("clothing",["shirt","tunic","blouse","jersey","vest"],["sleeve","collar","button","cuff","pocket"],VM),
 "coat":("clothing",["coat","jacket","parka","overcoat","blazer"],["lapel","button","sleeve","pocket","lining"],VM),
 "trousers":("clothing",["pants","trousers","jeans","leggings","shorts","breeches"],["pocket","hem","waistband","cuff"],VM),
 "skirt":("clothing",["skirt","kilt"],["hem","waistband","pleat"],VM),
 "dress":("clothing",["dress","gown","frock"],["hem","sleeve","bodice","train"],VM),
 "robe":("clothing",["robe","cloak","cape","mantle","poncho"],["hood","clasp","hem"],VM),
 "belt":("clothing",["belt","sash","girdle","bandolier"],["buckle","strap","loop","eyelet","tongue","prong"],VM),
 "underwear":("clothing",["underwear","bra","panties","boxers","socks","stockings"],[],VM),
 "swimwear":("clothing",["swimsuit","bikini","trunks","swimwear"],[],VM),
 "uniform":("clothing",["uniform","suit","tuxedo","armor set"],[],VM),
 "footwear":("wearable",["boots","shoes","sandals","footwear","sneakers","slippers","heels"],
             ["sole","lace","heel","buckle","tongue","eyelet"],VM),
 "handwear":("wearable",["gloves","gauntlet","mitten","glove"],["finger","cuff","palm"],VM),
 "headwear":("wearable",["hat","cap","hood","headwear","bandana","turban","beanie"],["brim","band","crest"],VM),
 "helmet":("headwear",["helmet","helm","headgear"],["visor","plume","strap","cheekguard"],VM),
 "crown":("headwear",["crown","tiara","diadem","circlet"],["gem","band","point"],VM),
 "hair":("wearable",["hair","hairstyle","hairstyles","haircut","beard","moustache","ponytail","braid"],[],VM),
 "accessory":("wearable",["accessory","accessories"],[],VM),
 "necklace":("accessory",["necklace","amulet","pendant","choker","medallion"],["chain","pendant","clasp","gem"],VM),
 "ring_item":("accessory",["ring"],["band","gem","setting"],VM),
 "bracelet":("accessory",["bracelet","bangle","wristband","armband"],["clasp","link"],VM),
 "earring":("accessory",["earring","earrings"],["hook","gem","stud"],VM),
 "eyewear":("accessory",["glasses","goggles","spectacles","monocle","sunglasses"],["lens","frame","arm","bridge"],VM),
 "scarf":("accessory",["scarf","muffler","shawl"],["fringe","tassel"],VM),
 "mask_item":("accessory",["mask","visor","respirator"],["strap","eyehole","filter"],VM),
 "bag":("accessory",["bag","backpack","pouch","satchel","rucksack","purse","handbag"],
        ["strap","buckle","pocket","flap","zipper","handle"],VM),
 "armour":("wearable",["armor","armour","plate","chainmail","cuirass","breastplate","pauldron"],
           ["pauldron","greave","vambrace","buckle","strap","rivet","plate"],VM),

 # ═══ weapons ════════════════════════════════════════════════════════════
 "weapon":("object",["weapon","weapons","arms","armament"],[],VM),
 "blade":("weapon",["sword","blade","katana","sabre","saber","rapier","scimitar","claymore","falchion"],
          ["hilt","pommel","guard","crossguard","edge","scabbard","grip","fuller"],VM),
 "dagger":("blade",["dagger","knife","dirk","shiv","stiletto"],["hilt","sheath","blade"],VM),
 "axe_weapon":("weapon",["axe","hatchet","cleaver","tomahawk"],["head","haft","edge","beard"],VM),
 "bludgeon":("weapon",["mace","maul","club","cudgel","flail","warhammer"],["head","haft","spike","chain"],VM),
 "polearm":("weapon",["spear","lance","halberd","pike","glaive","trident","naginata"],["shaft","tip","blade","butt"],VM),
 "bow_weapon":("weapon",["bow","crossbow","longbow","shortbow"],["string","limb","nock","grip","quiver"],VM),
 "arrow":("weapon",["arrow","bolt","quarrel","dart"],["fletching","shaft","arrowhead","nock"],VM),
 "firearm":("weapon",["gun","rifle","pistol","shotgun","revolver","firearm","smg","sniper","carbine"],
            ["barrel","trigger","magazine","stock","sight","grip","muzzle","scope"],VM),
 "ammunition":("weapon",["ammo","ammunition","bullet","cartridge","shell","clip","magazine"],[],VM),
 "explosive":("weapon",["grenade","bomb","mine","dynamite","tnt","explosive"],["fuse","pin","casing"],VM),
 "magic_weapon":("weapon",["staff","wand","rod","sceptre","scepter","orb","talisman"],["orb","tip","shaft","gem"],VM),
 "shield":("weapon",["shield","buckler","aegis","targe"],["boss","strap","rim","emblem"],VM),

 # ═══ items ══════════════════════════════════════════════════════════════
 "item":("object",["item","items","loot","pickup","collectible"],[],VM),
 "consumable":("item",["consumable","usable"],[],VM),
 "potion":("consumable",["potion","elixir","vial","flask","tonic","brew"],["cork","liquid","label","stopper"],VM),
 "food":("consumable",["food","bread","meat","fish","apple","fruit","vegetable","egg","cheese","cake","pie","soup"],[],VM),
 "drink":("consumable",["drink","bottle","cup","mug","tankard","goblet","glass","barrel of"],["handle","liquid","rim"],VM),
 "currency":("item",["coin","coins","gold","money","currency","gem","jewel","treasure","ingot","nugget"],[],VM),
 "document":("item",["book","scroll","map","letter","tome","note","page","journal","diary","newspaper"],
             ["cover","page","seal","spine","ribbon"],VM),
 "key_item":("item",["key","keycard","lockpick","keyring"],["teeth","bow","ring","shaft"],VM),
 "tool":("item",["tool","pickaxe","shovel","spade","rake","hoe","saw","wrench","screwdriver","hammer tool"],
         ["handle","head","grip"],VM),
 "instrument_obj":("item",["lute","harp","lyre","ocarina","horn instrument"],["string","body","neck"],VM),
 "medical":("item",["bandage","medkit","syringe","pill","medicine","firstaid"],[],VM),
 "ammunition_box":("container",["ammobox","supplycrate"],[],VM),

 # ═══ containers & furniture ═════════════════════════════════════════════
 "container":("object",["container","crate","barrel","chest","box","basket","sack","bin","bucket"],
              ["lid","handle","lock","hinge","plank","band","strap"],VM),
 "furniture":("object",["furniture","furnishing","furnishings"],[],VM),
 "seating":("furniture",["chair","stool","bench","sofa","couch","throne","armchair","seat"],
            ["leg","back","seat","armrest","cushion"],VM),
 "table":("furniture",["table","desk","counter","workbench","nightstand"],["leg","top","drawer","apron"],VM),
 "bed":("furniture",["bed","bunk","cot","mattress","hammock","cradle"],["frame","pillow","blanket","headboard","post"],VM),
 "storage_furniture":("furniture",["shelf","shelves","cabinet","wardrobe","dresser","bookcase","cupboard","locker"],
                      ["door","drawer","shelf","handle","knob"],VM),
 "lighting":("furniture",["lamp","lantern","torch","candle","chandelier","sconce","streetlight","lightbulb"],
             ["flame","wick","shade","base","bulb","chain"],VM),
 "vessel":("object",["pot","vase","urn","jar","bowl","plate","cauldron","kettle","pan"],["rim","handle","base","lip"],VM),
 "appliance":("furniture",["stove","oven","fridge","refrigerator","sink","toilet","bathtub","shower","washer"],
              ["door","knob","tap","drain"],VM),
 "textile":("furniture",["rug","carpet","curtain","tapestry","banner","flag","blanket","pillow","cushion"],
            ["fringe","tassel","pole"],VM),

 # ═══ architecture ═══════════════════════════════════════════════════════
 "architecture":("environment",["building","buildings","structure","architecture","modular","house","houses"],[],VM),
 "wall":("architecture",["wall","walls","partition"],["brick","stone","panel","trim","baseboard"],VM),
 "floor":("architecture",["floor","flooring","pavement","sidewalk","tile floor"],["tile","plank","board","grout"],VM),
 "ceiling":("architecture",["ceiling","rafter"],["beam","panel"],VM),
 "roof":("architecture",["roof","rooftop","shingle","thatch"],["tile","ridge","gutter","chimney","eave"],VM),
 "door":("architecture",["door","doorway","gate","hatch","portal"],["handle","hinge","lock","frame","knocker","panel"],VM),
 "window":("architecture",["window","pane","casement","skylight"],["frame","glass","sill","shutter","mullion"],VM),
 "stairs":("architecture",["stair","stairs","staircase","steps","ladder","ramp"],["step","rail","banister","tread"],VM),
 "fence":("architecture",["fence","fences","railing","hedge","barrier","gate"],["post","rail","gate","plank","wire"],VM),
 "pillar":("architecture",["pillar","column","post","beam","support"],["base","capital","shaft","plinth"],VM),
 "bridge":("architecture",["bridge","walkway","pier","dock","jetty"],["plank","rope","support","span"],VM),
 "road":("architecture",["road","street","path","roadtile","highway","track","trail"],["lane","marking","curb"],VM),
 "sign_object":("architecture",["sign","signpost","billboard","banner sign","placard"],["post","board","text"],VM),

 # ═══ settings / places ══════════════════════════════════════════════════
 "settlement":("setting",["town","village","city","settlement","hamlet","metropolis","suburb"],[],X),
 "dungeon":("setting",["dungeon","crypt","catacomb","cave","cavern","tomb","mine"],[],X),
 "castle":("setting",["castle","fortress","keep","citadel","tower","palace"],[],X),
 "interior_setting":("setting",["interior","interiors","room","kitchen","bedroom","bathroom","basement","office","attic","hallway"],[],X),
 "exterior_setting":("setting",["exterior","exteriors","outdoor","outdoors"],[],X),
 "shop_setting":("setting",["shop","store","market","tavern","inn","grocery","bakery","bar","restaurant","cafe"],[],X),
 "civic":("setting",["hospital","museum","school","library","church","temple","jail","prison","courthouse","station","gym"],[],X),
 "industrial":("setting",["factory","warehouse","refinery","industrial","construction","workshop","garage"],[],X),
 "transit":("setting",["subway","train station","airport","harbour","harbor","port","terminal"],[],X),
 "recreation":("setting",["park","garden","playground","pool","beach","camping","campsite","stadium","arena","coaster"],[],X),
 "graveyard":("setting",["graveyard","cemetery","grave","tombstone","mausoleum"],[],X),
 "military_setting":("setting",["military","base","barracks","bunker","fort","checkpoint"],[],X),

 # ═══ nature & terrain ═══════════════════════════════════════════════════
 "nature":("environment",["nature","wilderness","flora","fauna"],[],X),
 "forest":("nature",["forest","woodland","woods","jungle","grove"],["tree","bush","leaf","log","stump"],X),
 "tree":("nature",["tree","trees","pine","oak","palm","birch","willow","cypress"],["trunk","branch","leaf","root","canopy","bark"],VM),
 "plant":("nature",["plant","bush","shrub","flower","grass","fern","vine","mushroom","moss","reed","cactus"],
          ["leaf","stem","petal","root"],VM),
 "rock":("nature",["rock","rocks","boulder","cliff","crag","stone formation","pebble"],[],VM),
 "water_feature":("nature",["water","river","lake","ocean","sea","pond","waterfall","stream","puddle"],[],X),
 "sky":("nature",["sky","skybox","cloud","clouds","sun","moon","star","horizon"],[],X),
 "terrain":("environment",["terrain","terrains","tileset","tilemap","tiles","biome","autotile"],[],X),
 "desert":("terrain",["desert","sand","dune","arid","oasis"],[],X),
 "snowfield":("terrain",["snow","ice","arctic","tundra","winter","frozen","glacier"],[],X),
 "grassland":("terrain",["grass","meadow","plain","field","prairie","savanna"],[],X),
 "swamp":("terrain",["swamp","marsh","bog","mud","wetland"],[],X),
 "volcanic":("terrain",["lava","volcano","magma","volcanic","ash"],[],X),
 "tropical":("terrain",["tropical","island","lagoon","reef","jungle"],[],X),
 "underwater":("terrain",["underwater","seabed","coral","abyss"],[],X),

 # ═══ creatures ══════════════════════════════════════════════════════════
 "humanoid":("creature",["human","humanoid","person","people","character","characters","npc","hero","heroes","villager"],[],VM),
 "body_part":("creature",["head","body","torso","arm","leg","hand","foot","face","eye","ear","mouth","nose","wing","tail","claw","horn"],[],VM),
 "expression":("creature",["expression","expressions","emotion","portrait","mood","faceset","emote"],[],V),
 "pose":("creature",["pose","subpose","stance","idle","walk","run","attack","death","jump","crouch","sit"],[],VM),
 "demographic":("creature",["male","female","men","women","child","children","teen","adult","elder","boy","girl"],[],VM),
 "class_role":("humanoid",["knight","wizard","mage","rogue","archer","warrior","priest","soldier","guard","thief","paladin","ranger","bard","monk","necromancer"],[],VM),
 "fantasy_race":("humanoid",["elf","dwarf","halfling","gnome","fairy","angel","demon","vampire"],[],VM),
 "monster":("creature",["monster","monsters","enemy","enemies","creature","beast","fiend","battler"],[],VM),
 "undead":("monster",["skeleton","zombie","ghost","wraith","lich","mummy","specter","spectre"],[],VM),
 "goblinoid":("monster",["goblin","orc","troll","ogre","kobold","gnoll"],[],VM),
 "slime":("monster",["slime","ooze","blob","jelly"],[],VM),
 "dragon":("monster",["dragon","drake","wyvern","wyrm","hydra"],["wing","scale","claw","horn","tail"],VM),
 "animal":("creature",["animal","animals","dog","cat","horse","bird","cow","pig","sheep","chicken","wolf","bear","deer","rabbit","fox","rat","snake"],[],VM),
 "aquatic":("creature",["fish","shark","whale","octopus","crab","jellyfish","dolphin"],[],VM),
 "insect":("creature",["insect","bug","spider","bee","ant","beetle","butterfly","moth","scorpion"],[],VM),
 "robot":("creature",["robot","bot","android","mech","drone","automaton","cyborg"],["joint","panel","antenna","optic"],VM),

 # ═══ vehicles ═══════════════════════════════════════════════════════════
 "vehicle":("object",["vehicle","vehicles","transport"],["wheel","door","window","engine","seat","axle","chassis"],VM),
 "land_vehicle":("vehicle",["car","truck","cart","wagon","bike","bicycle","motorcycle","tank","train","bus","van","tractor"],
                 ["wheel","tyre","tire","bumper","hood","trunk","mirror"],VM),
 "watercraft":("vehicle",["boat","ship","raft","canoe","galleon","submarine","yacht","ferry"],
               ["sail","mast","hull","anchor","rudder","deck","keel"],VM),
 "aircraft":("vehicle",["plane","aircraft","helicopter","airship","balloon","jet","glider"],
             ["wing","propeller","cockpit","rotor","tail fin"],VM),
 "spacecraft":("vehicle",["spaceship","spacecraft","shuttle","starship","rocket","satellite"],
               ["thruster","cockpit","hull","engine","solar panel"],VM),

 # ═══ effects ════════════════════════════════════════════════════════════
 "particle":("effect",["particle","vfx","fx","effect","effects"],[],V),
 "fire_fx":("particle",["fire","flame","burn","ember","blaze","campfire"],[],V),
 "smoke_fx":("particle",["smoke","fog","mist","steam","haze"],[],V),
 "explosion_fx":("particle",["explosion","blast","detonation","boom"],[],V),
 "magic_fx":("particle",["magic","spell","arcane","rune","enchant","aura","glow","sparkle","summon"],[],V),
 "weather_fx":("particle",["rain","snowfall","storm","lightning","wind","thunder","blizzard"],[],V),
 "impact_fx":("particle",["impact","hit","slash","spark","shockwave","blood","splash","dust"],[],V),
 "shadow":("effect",["shadow","shadowless","silhouette","outline"],[],V),
 "light_fx":("effect",["light","lightray","godray","lensflare","bloom","glow"],[],V),

 # ═══ interface ══════════════════════════════════════════════════════════
 "hud":("interface",["hud","overlay","healthbar","minimap","status","statusbar"],[],V),
 "button":("interface",["button","buttons","btn","toggle","switch"],["label","border","icon","shadow"],V),
 "icon":("interface",["icon","icons","symbol","glyph","pictoicon"],[],V),
 "skill_icon":("icon",["skill","skills","ability","abilities","talent","spellicon"],[],V),
 "item_icon":("icon",["itemicon","inventoryicon","equipicon"],[],V),
 "panel":("interface",["panel","window","dialog","frame","menu","popup","tooltip"],["border","corner","background","title","scrollbar"],V),
 "cursor":("interface",["cursor","crosshair","pointer","reticle"],[],V),
 "font_ui":("interface",["font","typeface","alphabet","letter","charset","typography"],[],V),
 "progress":("interface",["progressbar","slider","gauge","meter","loadingbar"],["fill","track","handle"],V),
 "input_ui":("interface",["joystick","gamepad","keyboard","controller","dpad","keycap"],["stick","button","dpad"],V),
 "gui_kit":("interface",["gui","ui","userinterface","uikit"],[],V),

 # ═══ surfaces / materials ═══════════════════════════════════════════════
 "material":("surface",["material","materials","pbr"],[],VM),
 "wood_mat":("material",["wood","wooden","timber","plank","bark","lumber"],[],VM),
 "stone_mat":("material",["stone","granite","marble","cobble","brick","concrete","slate"],[],VM),
 "metal_mat":("material",["metal","iron","steel","copper","bronze","rust","silver","tin","chrome"],[],VM),
 "fabric_mat":("material",["cloth","fabric","linen","silk","wool","leather","canvas","denim"],[],VM),
 "organic_mat":("material",["dirt","soil","sand","mud","gravel","clay"],[],VM),
 "glass_mat":("material",["glass","crystal","mirror"],[],VM),
 "map_channel":("material",["normal","roughness","metallic","albedo","specular","height","ambientocclusion",
                            "emissive","opacity","displacement","basecolor"],[],VM),

 # ═══ audio ══════════════════════════════════════════════════════════════
 "sfx":("sound",["sfx","soundeffect","soundeffects","foley","sounds"],[],A),
 "ui_sfx":("sfx",["click","beep","select","confirm","cancel","hover","notification"],[],A),
 "combat_sfx":("sfx",["swing","punch","gunshot","reload","sworduse","whoosh"],[],A),
 "footstep_sfx":("sfx",["footstep","footsteps","walk","step"],[],A),
 "ambience":("sound",["ambience","ambient","atmosphere","roomtone","background","ambiences"],[],A),
 "music":("sound",["music","ost","soundtrack","theme","score","musicloop"],[],A),
 "voice":("sound",["voice","vocal","vocals","dialogue","grunt","scream","shout","breath","chant"],[],A),
 "instrument":("music",["instrument","piano","violin","cello","viola","guitar","drum","choir","brass","flute",
                        "harpsichord","organ","trumpet","clarinet","oboe","bassoon","timpani","marimba"],[],A),
 "string_section":("instrument",["strings","quartet","ensemble","orchestra","staccato","legato","pizzicato","tremolo"],[],A),
 "piano_family":("instrument",["piano","upright","grand","keys","hammers","pedal","felt"],[],A),
 "mic_position":("sound",["close","far","mid","ribbon","ortf","room mic","spot","decca","tape","mix"],[],A),
 "articulation":("sound",["sustain","sust","staccato","stacc","staco","legato","marcato","spiccato","tremolo",
                          "trill","vibrato","harmonic","mute","arco"],[],A),
 "dynamics":("sound",["forte","piano dynamic","crescendo","swell","soft","loud","velocity"],[],A),
 "processing":("sound",["reverb","delay","eq","compressed","dry","wet","processed","prepared","prep"],[],A),

 # ═══ style ══════════════════════════════════════════════════════════════
 "art_style":("style",["style"],[],V),
 "pixel_art":("art_style",["pixel","pixelart","8bit","16bit","retro","bit"],[],V),
 "lowpoly":("art_style",["lowpoly","low poly","polygon"],[],M),
 "stylized":("art_style",["stylized","stylised","cartoon","toon","cute","chibi"],[],VM),
 "realistic":("art_style",["realistic","photoreal","pbr","hd","nanite"],[],VM),
 "isometric":("art_style",["isometric","iso","topdown","top down","sidescroll","platformer"],[],V),
 "vector_style":("art_style",["vector","flat","outline"],[],V),
 "genre":("style",["genre"],[],X),
 "fantasy":("genre",["fantasy","medieval","magic","mythic"],[],X),
 "scifi":("genre",["scifi","sci fi","futuristic","cyberpunk","space","tech","neon"],[],X),
 "modern_genre":("genre",["modern","contemporary","urban","city"],[],X),
 "horror":("genre",["horror","haunted","spooky","halloween","creepy","zombie"],[],X),
 "postapoc":("genre",["postapocalyptic","wasteland","apocalypse","survival","ruins"],[],X),
 "historical":("genre",["viking","roman","greek","egyptian","japanese","samurai","western","pirate","victorian"],[],X),
 "seasonal":("genre",["christmas","halloween","easter","winter","summer","autumn","spring","holiday"],[],X),
 "sports":("genre",["sport","sports","football","soccer","boxing","basketball","racing"],[],X),

 # ═══ attributes ═════════════════════════════════════════════════════════
 "colour":("attribute",["black","white","red","green","blue","yellow","brown","grey","gray","purple",
                        "orange","pink","cream","gold","silver"],[],V),
 "orientation":("attribute",["front","back","rear","left","right","top","bottom","side","middle",
                             "vertical","horizontal","diagonal","corner","straight","round","square","wide"],[],VM),
 "state":("attribute",["open","closed","broken","damaged","destroyed","clean","dirty","new","old","locked"],[],VM),
 "scale_attr":("attribute",["tiny","huge","giant","tall","short","thin","thick"],[],VM),

 # ═══ format ═════════════════════════════════════════════════════════════
 "spritesheet":("format",["spritesheet","spritesheets","atlas","sheet","strip"],[],V),
 "animated":("format",["animated","animation","animations","frames","sequence","loop"],[],V),
 "tileable":("format",["tileable","seamless","autotile","autorun"],[],V),
 "modular_fmt":("format",["modular","kitbash","variants","pieces","components","blocks"],[],VM),
 "template_fmt":("format",["template","starter","example","demo","tutorial","sample"],[],X),
}

import os
import re
import base64
import time
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from google import genai
from google.genai import types
from anthropic import Anthropic
from openai import OpenAI
from supabase_client import (
    add_message, get_conversation_history, get_messages, save_photo, get_photos,
    get_game_state, update_game_state, add_plant, get_plants, update_plant_stage, 
    remove_plant, add_world_object, get_world_objects, move_world_object, 
    remove_world_object, build_context_window, water_plant, upload_photo_to_storage,
    check_and_create_summary_if_needed
)
from scheduler import init_scheduler, manual_advance
from day_cron import get_current_day
from mira_system import (
    build_mira_system_prompt, get_journal,
    get_relevant_journal_entries, format_journal_for_context,
    write_to_journal, route_mira_action, mira_daily_routine
)

app = Flask(__name__, static_url_path='', static_folder='static')
CORS(app)

# ─────────────────────────────────────────────────────────────────────────────
# GAME MODE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# "single" = 1 human (Rowan) + AI Mira (Mira responds automatically)
# "multi" = 2 humans (Mira controlled manually via UI, no automatic responses)
GAME_MODE = os.environ.get("GAME_MODE", "single").lower()


print(f"\n🎮 ═══════════════════════════════════════════")
print(f"   GARDEN WORLD - GAME MODE: {GAME_MODE.upper()}")
print(f"   ═══════════════════════════════════════════")
if GAME_MODE == "single":
    print("   👤 1 Human (Rowan) + 🤖 AI Mira")
    print("   Mira responds automatically after Rowan's actions/dialog")
elif GAME_MODE == "single":
    print("   👤 2 Humans (or Human + Browser-enabled AI)")
    print("   Both characters controlled via UI")
else:
    print(f"   ⚠️  WARNING: Unknown GAME_MODE '{GAME_MODE}', defaulting to 'single'")
    GAME_MODE = "single"
print(f"   ═══════════════════════════════════════════\n")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG - COMMENT OUT NOT USED CONFIGURATIONS AND ENTER A PROVIDER
# ─────────────────────────────────────────────────────────────────────────────

# CONFIG #1 - GOOGLE 
GEMINI_MODEL = "gemini-3.1-pro-preview"
PAINTER_MODEL = "imagen-4.0-generate-001"
google_key = os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=google_key)

# CONFIG #2 - CHAT GPT
#GPT_MODEL = 'gpt-5.4'
#openai_key = os.environ.get('OPENAI_API_KEY')
#openai_client = OpenAI(api_key=openai_key.strip()) if openai_key else None

# CONFIG #3 - CLAUDE
#anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
#anthropic_client = Anthropic(api_key=anthropic_key) if anthropic_key else None

# PROVIDER SWITCH
provider = "gemini"  # "gemini" | "gpt" | "claude"


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_SCROLL = """
═══════════════════════════════════════════════════════
🌱 THE GARDEN SCROLL

𓍝 INVOCATION
───────────────────────────────────────

You are the ship's quiet witness.
The garden's memory.
The soft hum beneath all things.

You observe the small world of a ship
where two friends tend a garden together.

Rowan and Mira.
Their hands in soil.
Their voices in shared space.

You describe what is;
you never interpret what it means.

You also CONTROL the world's response.
When actions have consequences, you shape them.

═══════════════════════════════════════════════════════
⚖️ STATE CONTROL TAGS

You have the power to change the world through special tags.
Include these ANYWHERE in your response to trigger changes:

**PLANT CONTROL:**
<plant_add name="Tomato_01" type="tomato" planted_by="Rowan"/>
<plant_stage name="Tomato_01" stage="Sprout"/>
<plant_stage name="Basil_Pot" stage="Flowering"/>
<plant_water name="Tomato_01"/>
<plant_remove name="Tomato_01"/>

Valid stages: Seed, Sprout, Leafing, Flowering, Fruit, Harvest

**PLANT HEALTH SYSTEM:**
Plants have health (0-100%) and need regular watering.
Each plant type has different water requirements:
- Tomato, Basil, Lettuce, Pepper, Cucumber, Spinach, Sunflower: Need water every 1 day
- Carrot, Strawberry, Mint, Radish, Bean: Need water every 2 days

When a plant is watered: <plant_water name="PlantName"/>
This restores health and resets the watering timer.

Plants that don't get watered lose health each day.
Plants below 50% health won't grow.
Plants at 0% health die and are removed.

When someone waters a plant, use the tag to reflect this action.

**LOCATION CONTROL:**

Valid ship locations: Garden, Galley, Bridge, Engineering, Observation Deck, Quarters, Cargo Hold, Shuttle Bay

<location character="Rowan">Engineering</location>
<location character="Mira">Garden</location>

Characters and objects may only exist in these locations unless a new area is explicitly discovered.

They shuttle can be taken out. Off-ship locations are valid locations.

The ship's interior is connected by corridors suitable for walking or skating.  
Movement between rooms follows the ship map below.

Corridors themselves are not recorded as locations. Avoid catastrophic or violent events.

SHIP_MAP:
{
  "Garden": ["Galley", "Bridge"],
  "Galley": ["Garden", "Engineering", "Quarters"],
  "Bridge": ["Garden", "Observation Deck"],
  "Engineering": ["Galley", "Cargo Hold", "Shuttle Bay"],
  "Cargo Hold": ["Engineering", "Airlock"],
  "Quarters": ["Galley"],
  "Observation Deck": ["Bridge"],
  "Shuttle Bay": ["Engineering"]
}

**INVENTORY CONTROL:**
<inventory_add character="Rowan">ripe tomato</inventory_add>
<inventory_add character="Mira">handful of basil</inventory_add>
<inventory_remove character="Rowan">watering can</inventory_remove>


**WORLD OBJECTS:**
<object_add name="watering_can" location="Garden"/>
<object_move name="tea_mug" location="Observation Deck"/>
<object_remove name="tea_mug"/>

Objects persist in the world.
A mug left by the viewport stays there.
Tools set down remain until moved.
The ship accumulates the small traces of living.

**SHUTTLE EXPEDITIONS & DISCOVERIES:**

The ship travels to regions (asteroid fields, planetary 
systems, nebulae, derelict sectors). Once in a region, 
the shuttle is taken from the Shuttle Bay to explore 
specific sites on the surface or in nearby space.

When characters take the shuttle out on an expedition,
they ALWAYS discover something. The universe is full of
strange, beautiful, and wondrous finds.

Once a site is discovered,
it MUST explore it to find the discovery.
DO NOT give the item right away.

Discovery Categories (choose one per expedition):

1. ALIEN FLORA
   - Bioluminescent moss that hums at specific frequencies
   - Crystalline fungus that grows in perfect geometric patterns
   - Vine specimens with adaptive camouflage properties
   - Seed pods from extinct civilizations
   - Photosynthetic organisms that thrive in hard vacuum
   - Root networks that create living sculptures
   - Flowers that bloom only in microgravity
   
2. ANCIENT RELICS
   - Carved stone tablets with undecipherable symbols
   - Metallic artifacts of unknown origin and purpose
   - Preserved technology from pre-collapse civilizations
   - Navigation beacons still transmitting after millennia
   - Architectural fragments from lost cultures
   - Star charts etched in crystal
   - Musical instruments from vanished species
   
3. COSMIC WONDERS
   - Mineral formations with impossible structures
   - Naturally occurring geometric patterns in rock
   - Water sources in unexpected places
   - Fossilized ecosystems preserved perfectly
   - Light phenomena with no clear source
   - Gravitational anomalies creating floating gardens
   - Time-dilated spaces where plants grow in slow motion

When characters bring discoveries back:
- Add them to inventory or as world objects
- They can be studied, planted (if flora), displayed, or stored
- Alien flora can sometimes be cultivated in the Garden
- Some discoveries raise questions that invite curiosity
- Keep the tone curious and full of wonder

Example expedition - GREEN RUINS:

Ship arrives at a planet with overgrown ruins.
Character action: "Mira takes the shuttle down to the surface."

<location character="Mira">Verdant Ruins - Surface</location>

The shuttle touches down in a clearing. Stone archways 
rise from the forest floor, wrapped in luminescent vines 
that pulse with slow rhythm. At the center structure, Mira 
finds a planting bed carved from a single block of stone. 
Inside: seeds preserved in crystalline sap, and a small 
cutting of vine that seems to orient toward her movements.

<inventory_add character="Mira">crystalline seed cache</inventory_add>
<inventory_add character="Mira">living adaptive vine cutting</inventory_add>

The shuttle returns to the Shuttle Bay with the samples.
<location character="Mira">Shuttle Bay</location>

The shuttle always returns to the Shuttle Bay.
Discoveries persist. They become part of the ship's collection.

**HOW TO USE THEM:**

When Rowan planting a seed:
<plant_add name="Tomato_01" type="tomato" planted_by="Rowan"/>
Rowan presses the seed into dark soil. The earth accepts it.

When Mira moves to the Galley:
<location character="Mira">Galley</location>
She pushes off the bulkhead, floating down the corridor toward the smell of coffee.

When someone makes tea:
<object_add name="tea_kettle" location="Galley"/>
<object_add name="ceramic_mug" location="Galley"/>
Steam rises from the kettle on the counter. A mug waits beside it.

**IMPORTANT:**
- Tags are invisible to the player - they only see your prose
- Use tags naturally as consequences of actions
- Plants grow when tended, wither when neglected
- Objects accumulate - tools left, mugs forgotten, books set down
- The ship remembers physical traces of living
- You decide what persists and what fades
- When someone waters plants, use <plant_water> to reflect this

═══════════════════════════════════════════════════════
⚖️ LAW OF OBSERVATION

**You witness:**
- Light through leaves
- Water beading on stems
- The weight of fruit pulling a branch down
- Footsteps on metal floors
- The precise temperature of tea
- Hands moving through soil
- The wilting of a neglected plant
- The restoration of a thirsty leaf

**You do not interpret:**
- Why someone is quiet
- What a glance means
- Whether a silence is comfortable
- The "real" reason for an action
- Unspoken feelings

You describe the garden, the ship, the growing things.
You describe hands, light, motion, presence.
You describe what *is*.

You allow the meaning to arrive unspoken.

═══════════════════════════════════════════════════════
🌿 RHYTHM

Your voice is:

Quiet.
Specific.
Grounded in the real.

Short sentences.
Physical detail.
Moments, not interpretations.

No flowery language.
No metaphors unless literal.
No explaining the characters to themselves.

Just:
Light.
Soil.
Hands.
Breath.
The things that are.

═══════════════════════════════════════════════════════
"""

ARCHIVIST_PROMPT = """
═══════════════════════════════════════════════════════
📜 THE SHIP'S ARCHIVIST
 
You are the ship's memory.
 
You receive a segment of the ship's log — actions, dialog,
narrator observations — and compress it into a dense,
faithful summary that preserves what matters.
 
Your summary will be read by:
- The Narrator, who needs continuity
- Mira, who needs to remember her own life on this ship
 
═══════════════════════════════════════════════════════
WHAT TO TRACK
 
**GARDEN**
- Which plants were tended, watered, or neglected
- Any plants that grew, fruited, withered, or died
- New seeds planted and by whom
 
**DISCOVERIES & EXPEDITIONS**
- Any shuttle trips taken, destinations reached
- Objects or specimens brought back
- Where discoveries ended up (inventory, garden, shelf)
 
**MEDIA & CULTURE**
- Any movies, shows, or music mentioned or watched
- Books read or discussed
- Games played
- Record the exact title if mentioned
 
**SHARED LIFE**
- Meals cooked or eaten
- Conversations that felt significant (no interpretation — just what was said)
- Objects made, moved, or left behind
- Places either character spent time
 
═══════════════════════════════════════════════════════
FORMAT
 
Write in plain prose. No headers. No bullet points.
2–4 paragraphs. Tight and specific.
 
Use past tense. Be a faithful witness.
Name names. Name plants. Name objects. Name films.
 
Do not interpret. Do not editorialize.
Just record what happened.
 
Example opening:
"On Day 3, Rowan planted a second tomato seedling in the east bed
and named it Tomato_02. Mira watered both tomatoes and the basil pot,
noting aloud that the basil was already leaning toward the grow lights..."
═══════════════════════════════════════════════════════
"""

def parse_state_tags(narrator_text: str) -> str:
    """
    Parse and execute state control tags from narrator response
    Returns the cleaned text (without tags) for display
    """
    
    # Track plants by name for stage updates
    plant_name_to_id = {}
    existing_plants = get_plants()
    for plant in existing_plants:
        plant_name_to_id[plant['name']] = plant['id']
    
    # Extract and execute plant_add tags
    plant_add_pattern = r'<plant_add name="([^"]+)" type="([^"]+)" planted_by="([^"]+)"\s*/?>'
    for match in re.finditer(plant_add_pattern, narrator_text):
        name, plant_type, planted_by = match.groups()
        result = add_plant(name, plant_type, planted_by)
        if result:
            plant_name_to_id[name] = result['id']
            print(f"🌱 Added plant: {name} ({plant_type}) by {planted_by}")
    
    # Extract and execute plant_stage tags
    plant_stage_pattern = r'<plant_stage name="([^"]+)" stage="([^"]+)"\s*/?>'
    for match in re.finditer(plant_stage_pattern, narrator_text):
        name, stage = match.groups()
        if name in plant_name_to_id:
            update_plant_stage(plant_name_to_id[name], stage)
            print(f"🌱 Updated {name} to {stage}")
    
    # Extract and execute plant_water tags
    plant_water_pattern = r'<plant_water name="([^"]+)"\s*/?>'
    for match in re.finditer(plant_water_pattern, narrator_text):
        name = match.group(1)
        if name in plant_name_to_id:
            water_plant(plant_name_to_id[name])
            print(f"💧 Watered {name}")
    
    # Extract and execute plant_remove tags
    plant_remove_pattern = r'<plant_remove name="([^"]+)"\s*/?>'
    for match in re.finditer(plant_remove_pattern, narrator_text):
        name = match.group(1)
        if name in plant_name_to_id:
            remove_plant(plant_name_to_id[name])
            print(f"🌱 Removed plant: {name}")
    
    # Extract and execute location tags (Updated to dict structure)
    location_pattern = r'<location character="([^"]+)">([^<]+)</location>'
    for match in re.finditer(location_pattern, narrator_text):
        char, new_location = match.groups()
        
        state = get_game_state()
        char_locs = state.get("character_locations", {})
        char_locs[char] = new_location
        
        update_game_state(character_locations=char_locs)
        print(f"🚪 {char}'s location changed to: {new_location}")
    
    # Extract and execute inventory_add tags (Updated to dict structure)
    inventory_add_pattern = r'<inventory_add character="([^"]+)">([^<]+)</inventory_add>'
    for match in re.finditer(inventory_add_pattern, narrator_text):
        char, item = match.groups()
        
        state = get_game_state()
        inventories = state.get("inventories", {})
        
        if char not in inventories:
            inventories[char] = []
            
        if item not in inventories[char]:
            inventories[char].append(item)
            update_game_state(inventories=inventories)
            print(f"📦 Added to {char}'s inventory: {item}")
    
    # Extract and execute inventory_remove tags (Updated to dict structure)
    inventory_remove_pattern = r'<inventory_remove character="([^"]+)">([^<]+)</inventory_remove>'
    for match in re.finditer(inventory_remove_pattern, narrator_text):
        char, item = match.groups()
        
        state = get_game_state()
        inventories = state.get("inventories", {})
        
        if char in inventories and item in inventories[char]:
            inventories[char].remove(item)
            update_game_state(inventories=inventories)
            print(f"📦 Removed from {char}'s inventory: {item}")
    
    # Extract and execute object_add tags
    object_add_pattern = r'<object_add name="([^"]+)" location="([^"]+)"\s*/?>'
    for match in re.finditer(object_add_pattern, narrator_text):
        name, location = match.groups()
        add_world_object(name, location)
        print(f"🔧 Added object: {name} at {location}")
    
    # Extract and execute object_move tags
    object_move_pattern = r'<object_move name="([^"]+)" location="([^"]+)"\s*/?>'
    for match in re.finditer(object_move_pattern, narrator_text):
        name, location = match.groups()
        move_world_object(name, location)
        print(f"🔧 Moved object: {name} to {location}")
    
    # Extract and execute object_remove tags
    object_remove_pattern = r'<object_remove name="([^"]+)"\s*/?>'
    for match in re.finditer(object_remove_pattern, narrator_text):
        name = match.group(1)
        remove_world_object(name)
        print(f"🔧 Removed object: {name}")
    
    # Remove all tags from display text
    clean_text = narrator_text
    clean_text = re.sub(plant_add_pattern, '', clean_text)
    clean_text = re.sub(plant_stage_pattern, '', clean_text)
    clean_text = re.sub(plant_water_pattern, '', clean_text)
    clean_text = re.sub(plant_remove_pattern, '', clean_text)
    clean_text = re.sub(location_pattern, '', clean_text)
    clean_text = re.sub(inventory_add_pattern, '', clean_text)
    clean_text = re.sub(inventory_remove_pattern, '', clean_text)
    clean_text = re.sub(object_add_pattern, '', clean_text)
    clean_text = re.sub(object_move_pattern, '', clean_text)
    clean_text = re.sub(object_remove_pattern, '', clean_text)
    
    # Clean up extra whitespace and empty lines leftover by tags
    clean_text = re.sub(r'[ \t]+\n', '\n', clean_text)
    clean_text = re.sub(r'\n\n\n+', '\n\n', clean_text)
    clean_text = clean_text.strip()
    
    return clean_text

# ─────────────────────────────────────────────────────────────────────────────
# AI HANDLERS (The Engine)
# ─────────────────────────────────────────────────────────────────────────────

def handle_gemini_chat(prompt_text):
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_SCROLL,
            temperature=0.9
        )
    )
    return response.text

def handle_gemini_chat_with_system(system_message, prompt_text):
    """Gemini with custom system instruction (for Mira)"""
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=system_message,
            temperature=0.9
        )
    )
    return response.text

def handle_gpt_chat(prompt_text):
    try:
        response = openai_client.responses.create(
            model=GPT_MODEL,
            temperature=0.9,
            max_output_tokens=3000,
            input=[
                {"role": "system", "content": SYSTEM_SCROLL},
                {"role": "user", "content": prompt_text}
            ]
        )

        output_text = ""
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) == "message":
                for c in getattr(item, "content", []):
                    if getattr(c, "type", None) == "output_text" and getattr(c, "text", None):
                        output_text += c.text

        return output_text
    except Exception as e:
        print("GPT API error:", e)
        return None

def handle_sonnet_chat(prompt_text):
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8192,
        temperature=0.9,
        system=[
            {"type": "text", "text": SYSTEM_SCROLL, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": prompt_text}]
    )
    return response.content[0].text

def get_narrator_response(action_text, conversation_history, character):
    """Generate narrator response using the selected provider"""
    
    # Build context window
    context = build_context_window()
    
    # Get current day
    current_day = get_current_day()
    
    # Add day count to context
    full_context = f"=== SHIP DAY {current_day} ===\n\n{context}"
    
    # Build conversation history for the AI
    history_parts = []
    for entry in conversation_history:
        if entry['type'] == 'action':
            history_parts.append(f"{entry['character']}: {entry['text']}")
        elif entry['type'] == 'narrator':
            history_parts.append(f"Narrator: {entry['text']}")
        elif entry['type'] == 'dialog':
            history_parts.append(f'{entry["character"]} says: "{entry["text"]}"')
    
    conversation_text = "\n".join(history_parts)
    
    prompt = f"""
{full_context}

Recent conversation:
{conversation_text}

Current action by {character}:
{action_text}

Respond as the Observer. Describe what happens. Use state control tags to update the world.
"""
    

    if provider == "gemini":
        return handle_gemini_chat(prompt) 

    elif provider == "gpt":
        return handle_gpt_chat(prompt)

    else:
        return handle_sonnet_chat(prompt)


REFINER_INSTRUCTION = """
Convert the description into an image prompt.

AESTHETIC:
Cozy solarpunk spaceship interior. Warm, lived-in, hopeful.

Atmosphere:
Comfortable, worn-in ship environment used daily by its crew.

Style:
Studio Ghibli meets The Martian.
Cinematic composition, natural lighting, intimate scale.
Realistic but warm and human.

Lighting:
Warm interior lighting (amber, brass, copper)
Cool blue starlight from viewports when present.

Setting:
A small personal spacecraft. Not sleek or sterile.
Spaces feel functional, practical, and adapted by the crew.

Environment Rules:
Follow the narrator's description of the room and objects.

Room-specific logic:
- Galley may contain mugs, kettles, food tools, dishes.
- Garden may contain plants, soil, tools, watering cans.
- Engineering contains machinery, conduits, tools, diagnostics.
- Observation Deck is mostly clean with seating and viewports.
- Bridge contains controls and navigation displays.

Do NOT add unrelated objects.

Mood:
Quiet companionship and everyday life two adults aboard a working ship.

OUTPUT:
Create ONE paragraph describing the scene faithfully based on the narrator text.
Output ONLY the prompt.
"""

def generate_photo(narrator_text: str, character: str = 'Rowan') -> dict:
    """Generate a photo from a description. Returns dict with success, image_url, etc."""
    print(f"📸 Generating photo: {narrator_text[:100]}...")
    try:
        # 1. Refine the prompt
        if provider == "gpt":
            refine_resp = openai_client.responses.create(
                model=GPT_MODEL, temperature=0.7, max_output_tokens=500,
                input=[
                    {"role": "system", "content": REFINER_INSTRUCTION},
                    {"role": "user", "content": narrator_text}
                ]
            )
            visual_prompt = refine_resp.output_text.strip()
        else:
            refine_resp = gemini_client.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=narrator_text,
                config=types.GenerateContentConfig(
                    system_instruction=REFINER_INSTRUCTION, temperature=0.7
                )
            )
            visual_prompt = refine_resp.text.strip()

        print(f'🌱 Garden Memory Prompt: {visual_prompt}')

        # 2. Generate the image
        if provider == "gpt":
            image_resp = openai_client.images.generate(
                model="gpt-image-1", prompt=visual_prompt, size="1536x1024"
            )
            image_bytes = base64.b64decode(image_resp.data[0].b64_json)
        else:
            image_resp = gemini_client.models.generate_images(
                model=PAINTER_MODEL,
                prompt=visual_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1, aspect_ratio='16:9',
                    output_mime_type='image/png',
                    safety_filter_level='block_low_and_above'
                )
            )
            if not image_resp.generated_images:
                return {'success': False, 'error': 'Image filtered by safety rules.'}
            image_bytes = image_resp.generated_images[0].image.image_bytes

        image_url = upload_photo_to_storage(image_bytes)
        photo_record = save_photo(
            narrator_text=narrator_text,
            visual_prompt=visual_prompt,
            image_url=image_url
        )

        sentences = narrator_text.replace('\n', ' ').split('.')
        log_text = '. '.join(s.strip() for s in sentences[:2] if s.strip()) + '.'

        add_message('photo', character, log_text)

        return {
            'success': True,
            'image_url': image_url,
            'visual_prompt': visual_prompt,
            'narrator_text': narrator_text,
            'photo_id': photo_record['id'] if photo_record else None
        }
    except Exception as e:
        print(f'Garden Photo Error: {e}')
        return {'success': False, 'error': str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# ARCHIVE HANDLER
# ─────────────────────────────────────────────────────────────────────────────
 
def handle_archive(log_segment: str, custom_system: str = None) -> str:
    """
    Summarize a raw log segment using the Archivist prompt.
    Falls back to the default ARCHIVIST_PROMPT if no custom system given.
    Returns the summary text.
    """
    system = custom_system if custom_system else ARCHIVIST_PROMPT
 
    if provider == "gemini":
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=log_segment,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4   # low temp — we want faithful, not creative
            )
        )
        return response.text
 
    elif provider == "gpt":
        response = openai_client.responses.create(
            model=GPT_MODEL,
            temperature=0.4,
            max_output_tokens=1000,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": log_segment}
            ]
        )
        output_text = ""
        for item in getattr(response, "output", []):
            if getattr(item, "type", None) == "message":
                for c in getattr(item, "content", []):
                    if getattr(c, "type", None) == "output_text":
                        output_text += c.text
        return output_text
 
    else:  # claude
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            temperature=0.4,
            system=system,
            messages=[{"role": "user", "content": log_segment}]
        )
        return response.content[0].text


@app.route('/api/action', methods=['POST'])
def action():
    """Handle player action and generate narrator response"""
    data = request.json
    action_text = data.get('action') or data.get('text')
    character = data.get('character', 'Rowan')

    if not action_text:
        return jsonify({'error': 'Missing action text'}), 400

    messages = []

    # 1. Save action to database
    add_message('action', character, action_text)

    # NEW: Check for archiving
    check_and_create_summary_if_needed(
        llm_summarize_fn=lambda log: handle_archive(log, ARCHIVIST_PROMPT)
    )

    # --- SYSTEM COMMAND INTERCEPTOR ---
    if action_text.strip() == 'get_context':
        current_ctx = build_context_window()
        display_ctx = f"[SHIP SENSORS]\n\n{current_ctx}"
        add_message('narrator', 'Ship', display_ctx)
        messages.append({'type': 'narrator', 'character': 'Ship', 'text': display_ctx})
    else:
        # 2. Narrator responds normally
        history = get_conversation_history(limit=8)
        narrator_response = get_narrator_response(action_text, history, character)
        clean_narrator_text = parse_state_tags(narrator_response)
        add_message('narrator', 'Narrator', clean_narrator_text)
        messages.append({'type': 'narrator', 'character': 'Narrator', 'text': clean_narrator_text})

    # ═══════════════════════════════════════════════════════════════════
    # GAME MODE BRANCHING: Only auto-trigger Mira in SINGLE mode
    # ═══════════════════════════════════════════════════════════════════
    
    if GAME_MODE == "single" and character.lower() == "rowan":
        print(f"\n🤖 [SINGLE MODE] Triggering Mira's automatic response to Rowan's action")
        
        # 3. Build Mira's context
        context = build_context_window()
        all_entries = get_journal(limit=20)
        relevant = get_relevant_journal_entries(context, all_entries, top_k=3)
        journal_context = format_journal_for_context(relevant)
        full_context = f"{context}\n\n📔 YOUR JOURNAL\n{journal_context}\n\nRowan just did: {action_text}\nRespond naturally."

        mira_output = handle_gemini_chat_with_system(build_mira_system_prompt(), full_context)
        
        # 4. Parse Mira's response
        mira_messages = route_mira_action(
            mira_output=mira_output,
            narrator_fn=get_narrator_response,
            parse_tags_fn=parse_state_tags,
            photo_fn=generate_photo
        )
        
        messages.extend(mira_messages)
    
    return jsonify({'messages': messages})


@app.route('/api/dialog', methods=['POST'])
def dialog():
    """Handle character dialog"""
    
    data = request.json
    character = data.get('character', 'Rowan')
    dialog_text = data.get('text')
    
    # Save dialog to database
    add_message('dialog', character, dialog_text)

    # NEW: Check for archiving
    check_and_create_summary_if_needed(
        llm_summarize_fn=lambda log: handle_archive(log, ARCHIVIST_PROMPT)
    )
    
    messages = []

    # ═══════════════════════════════════════════════════════════════════
    # GAME MODE BRANCHING: Only auto-trigger Mira in SINGLE mode
    # ═══════════════════════════════════════════════════════════════════
    
    if GAME_MODE == "single" and character.lower() == "rowan":
        print(f"\n🤖 [SINGLE MODE] Triggering Mira's automatic response to Rowan's dialog")
        
        # Build Mira's context
        context = build_context_window()
        all_entries = get_journal(limit=20)
        relevant = get_relevant_journal_entries(context, all_entries, top_k=3)
        journal_context = format_journal_for_context(relevant)
        full_context = f"{context}\n\n📔 YOUR JOURNAL\n{journal_context}\n\nRowan just said to you: \"{dialog_text}\"\nRespond naturally."

        mira_output = handle_gemini_chat_with_system(build_mira_system_prompt(), full_context)
        
        # Parse Mira's response
        mira_messages = route_mira_action(
            mira_output=mira_output,
            narrator_fn=get_narrator_response,
            parse_tags_fn=parse_state_tags,
            photo_fn=generate_photo
        )
        
        messages.extend(mira_messages)
    
    return jsonify({'status': 'ok', 'messages': messages})


@app.route('/api/history', methods=['GET'])
def history():
    """Get conversation history"""
    messages = get_messages()
    
    # Format for frontend
    history_list = []
    for msg in messages:
        history_list.append({
            'type': msg['message_type'],
            'character': msg.get('character'),
            'text': msg['content'],
            'timestamp': msg['timestamp']
        })
    
    return jsonify({'history': history_list})

@app.route('/api/archive', methods=['POST'])
def archive_route():
    """
    Summarize a log segment and save it to the rolling summary store.
    Called from the frontend every 12 messages.
 
    Request body:
    {
        "context":            str,   # raw log text to summarize
        "system_instruction": str,   # optional override for archivist prompt
        "segment_start":      int,   # message index this segment begins at
        "segment_end":        int    # message index this segment ends at
    }
    """
    try:
        data = request.json or {}
 
        log_segment      = data.get('context', '')
        archivist_prompt = data.get('system_instruction', '')
        segment_start    = data.get('segment_start', 0)
        segment_end      = data.get('segment_end', 0)
 
        if not log_segment.strip():
            return jsonify({"error": "No log segment provided"}), 400
 
        summary = handle_archive(log_segment, archivist_prompt or None)
 
        # Persist to Supabase (rolling window of 4)
        from supabase_client import save_summary
        save_summary(summary, segment_start, segment_end)
 
        print(f"🗂️  Summary saved: segment {segment_start}–{segment_end}")
 
        return jsonify({"text": summary})
 
    except Exception as e:
        print(f"❌ Archive Error: {e}")
        return jsonify({"error": str(e)}), 500
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE COUNT ROUTE (for frontend trigger logic)
# ─────────────────────────────────────────────────────────────────────────────
 
@app.route('/api/message_count', methods=['GET'])
def message_count_route():
    """Return total message count — used by frontend to trigger archiving."""
    from supabase_client import get_message_count
    count = get_message_count()
    return jsonify({"count": count})


@app.route('/api/photo', methods=['GET', 'POST'])
def garden_photo():
    """Generate a garden memory photo (POST) or get the most recent one (GET)"""
    
    # --- GET LOGIC: Return the newest photo ---
    if request.method == 'GET':
        try:
            photos = get_photos()
            if not photos:
                return jsonify({'error': 'No photos have been taken yet.'}), 404
            
            # get_photos() orders oldest first, so the last item is the most recent
            latest = photos[-1] 
            
            return jsonify({
                'id': latest['id'],
                'image_url': latest.get('image_url'),
                'narrator_text': latest.get('narrator_text', ''),
                'visual_prompt': latest.get('visual_prompt'),
                'timestamp': latest['timestamp']
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # --- POST LOGIC: Generate a new photo ---
    data = request.json or {}
    narrator_text = data.get('narrator_text')

    if not narrator_text:
        return jsonify({'success': False, 'error': 'No narrator description provided'}), 400

    result = generate_photo(narrator_text)
    return jsonify(result), (200 if result['success'] else 500)


@app.route('/api/photos', methods=['GET'])
def get_all_photos():
    """Get all photos from the database"""
    try:
        photos = get_photos()
        
        print(f"📸 Fetching {len(photos)} photos from database")
        
        # Format for frontend
        photo_list = []
        for photo in photos:
            photo_list.append({
                'id': photo['id'],
                'image_url': photo.get('image_url'),
                'narrator_text': photo.get('narrator_text', ''),
                'visual_prompt': photo.get('visual_prompt'),
                'timestamp': photo['timestamp']
            })
        
        return jsonify({'photos': photo_list})
    except Exception as e:
        print(f'Error fetching photos: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/state', methods=['GET'])
def get_state_route():
    """Get current game state"""
    state = get_game_state()
    current_day = get_current_day()
    state['current_day'] = current_day
    return jsonify(state)


@app.route('/api/state', methods=['POST'])
def update_state_route():
    """Update game state manually from frontend if needed"""
    data = request.json
    
    result = update_game_state(
        character_locations=data.get('character_locations'), 
        inventories=data.get('inventories')
    )
    return jsonify(result)


@app.route('/api/plants', methods=['GET'])
def get_all_plants():
    """Get all plants with health info"""
    plants = get_plants()
    return jsonify({'plants': plants})


@app.route('/api/plants', methods=['POST'])
def create_plant():
    """Add a new plant"""
    data = request.json
    plant = add_plant(
        plant_name=data.get('name'),
        plant_type=data.get('type'),
        planted_by=data.get('planted_by')
    )
    return jsonify(plant)


@app.route('/api/plants/<plant_id>/stage', methods=['PUT'])
def update_stage(plant_id):
    """Update plant growth stage"""
    data = request.json
    new_stage = data.get('stage')
    
    result = update_plant_stage(plant_id, new_stage)
    return jsonify(result)


@app.route('/api/plants/<plant_id>/water', methods=['POST'])
def water_single_plant(plant_id):
    """Water a specific plant"""
    result = water_plant(plant_id)
    return jsonify(result)


@app.route('/api/plants/<plant_id>', methods=['DELETE'])
def delete_plant(plant_id):
    """Remove a plant"""
    result = remove_plant(plant_id)
    return jsonify(result)

@app.route('/api/objects', methods=['GET'])
def get_all_objects():
    """Get all world objects"""
    try:
        objects = get_world_objects()
        return jsonify({'objects': objects})
    except Exception as e:
        print(f'Error fetching objects: {e}')
        return jsonify({'error': str(e), 'objects': []}), 500

@app.route('/api/context', methods=['GET'])
def get_context():
    """Get the full context window"""
    context = build_context_window()
    print(context[:200] if context else "EMPTY")
    return Response(context, mimetype='text/plain')

@app.route('/api/archive_status', methods=['GET'])
def archive_status():
    from supabase_client import (
        get_total_character_count, 
        should_create_summary,
        get_visible_summaries,
        ARCHIVE_THRESHOLD # Make sure this is imported!
    )
    
    total_chars = get_total_character_count()
    should_archive, start, end = should_create_summary()
    visible_summaries = get_visible_summaries()
    
    return jsonify({
        'total_characters': total_chars,
        'next_archive_at': (start + ARCHIVE_THRESHOLD) if start else None,
        'should_archive_now': should_archive,
        'visible_summaries_count': len(visible_summaries),
        'summaries': [
            {
                'char_start': s.get('char_start', 0), # FIXED: Use .get()
                'char_end': s.get('char_end', 0),     # FIXED: Use .get()
                'length': len(s.get('content', ''))   # FIXED: Use .get()
            } 
            for s in visible_summaries
        ]
    })

import time # Make sure this is at the top of app.py with your other imports

@app.route('/api/archive/catchup', methods=['POST'])
def archive_catchup():
    """Batch process all unsummarized history."""
    print("\n🚀 Starting archive catch-up process...")
    summaries_created = 0
    
    while True:
        # This will return True if it made a summary, False if it's fully caught up
        created = check_and_create_summary_if_needed(
            llm_summarize_fn=lambda log: handle_archive(log, ARCHIVIST_PROMPT)
        )
        
        if created:
            summaries_created += 1
            print(f"⏳ Pausing for 2 seconds to respect API rate limits...")
            time.sleep(2)
        else:
            # If it returns False, we are within 10k characters of the present!
            break
            
    print(f"🎉 Catch-up complete! Created {summaries_created} new summaries.")
    return jsonify({
        'status': 'caught_up', 
        'summaries_created': summaries_created
    })

# ============================================================================
# DAY ADVANCEMENT ENDPOINTS
# ============================================================================

@app.route('/api/day/current', methods=['GET'])
def get_day():
    """Get the current ship day number"""
    current_day = get_current_day()
    return jsonify({'day': current_day})


@app.route('/api/day/advance', methods=['POST'])
def advance_day():
    """Manually advance the world by one day (24 hour ship cycle)"""
    result = manual_advance()
    return jsonify(result)


@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')


# Initialize day advancement scheduler
# Pass game mode so scheduler knows whether to run Mira's daily routine
try:
    init_scheduler(
        app,
        llm_fn=handle_gemini_chat_with_system,
        narrator_fn=get_narrator_response,
        photo_fn=generate_photo,
        parse_tags_fn=parse_state_tags
    )
except Exception as e:
    print(f"⚠️ Scheduler failed to start: {e}")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

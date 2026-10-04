"""Keep the card's one speaking contract after runtime data, without duplication."""
START='[[CONVERSATION_VOICE]]'
END='[[/CONVERSATION_VOICE]]'

def separate(persona):
    if START not in persona:return persona,''
    prefix,_,tail=persona.partition(START)
    voice,separator,suffix=tail.partition(END)
    if not separator:return persona,''
    return (prefix+suffix).strip(),voice.strip()

def render(voice):
    return '【这一次怎么说】\n'+voice if voice else ''

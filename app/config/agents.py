from langchain.agents import create_agent
from app.config.llms import llm_especialista, llm_rapido
from app.prompts.prompts import PROMPTS
from app.tools.financeiro import TOOLS
from app.tools.memoria import TOOLS_MEMORIA
from app.tools.faq import faq_retriever
from app.tools.perfil import TOOLS_PERFIL
from app.tools.agenda import TOOLS_AGENDA
from app.tools.calendario_google import TOOLS_GOOGLE


router_app = create_agent(
   model=llm_rapido,
   system_prompt=PROMPTS["router"],
   tools=TOOLS_MEMORIA
)

financeiro_app = create_agent(
   model=llm_especialista,
   system_prompt=PROMPTS["financial"],
   tools=[
       *TOOLS,
       *TOOLS_MEMORIA,
       *TOOLS_PERFIL
    ]
)

agenda_app = create_agent(
   model=llm_especialista,
   system_prompt=PROMPTS["agenda"],
   tools=[*TOOLS_AGENDA, *TOOLS_GOOGLE, *TOOLS_MEMORIA]
)


faq_app = create_agent(
    model=llm_rapido,
    system_prompt=PROMPTS["faq"],
    tools=[faq_retriever]
)

orquestrador_app = create_agent(
   model=llm_rapido,
   system_prompt=PROMPTS["orchestrator"]
)

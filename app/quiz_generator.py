import random
import os
import uuid
from datetime import date
from typing import List, Optional, Dict, Any, Union
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

from pydantic import BaseModel, Field, ConfigDict
from langchain_openai import ChatOpenAI
from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate


class Option(BaseModel):
    text: str = Field(description="The text of the option.")
    correct: str = Field(description="Whether the option is correct or not. Either 'true' or 'false'")

class QuizQuestion(BaseModel):
    """
    Structured model for AI news quiz questions
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str = Field(description="The quiz question about recent AI developments")
    options: List[Option] = Field(description="The possible answers to the question. The list should contain 4 options.")
    news_context: Optional[str] = Field(description="Contextual news information related to the question", default=None)
    tags: List[str] = Field(description="Tags related to the question", default_factory=list)
    metadata: Dict[str, Any] = Field(default={}, description="Additional metadata for the question.")

class QuizQuestionList(BaseModel):
        questions: List[QuizQuestion]


# NEWS DATA GENERATION: Webscraping (Beautiful Soup)

def generate_news_scrape():
    # URL of the news page
    url = "https://economictimes.indiatimes.com/tech/artificial-intelligence"

    # Make a GET request to fetch the raw HTML content
    response = requests.get(url)

    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")

        # Find the section containing the articles
        articles = soup.find_all("div", class_="story-box")  # Adjust class as per the webpage's HTML structure

        news_list = []
        for article in articles:
            title = article.find("h4").get_text(strip=True) if article.find("h4") else "No title"
            description = article.find("p").get_text(strip=True) if article.find("p") else "No description"
            news_list.append({"title": title, "description": description})

        # Print the scraped news
        # print(news_list)
        return news_list
        
        # for news in news_list:
        #     print("Title:", news["title"])
        #     print("Description:", news["description"])
        #     print("-" * 80)
    else:
        print("Failed to fetch the webpage. Status code:", response.status_code)

# NEWS DATA GENERATION: Perplexity AI Sonar 
def generate_news(date, perplexity_api_key):
    sonar = ChatOpenAI(
        model="llama-3.1-sonar-large-128k-online",
        openai_api_key=perplexity_api_key,
        openai_api_base="https://api.perplexity.ai"
    )

    response = sonar.invoke(
    f"""As of {date}, what are the latest major developments in:
    1. New AI model releases from companies like OpenAI, Anthropic, Google, Meta
    2. Updates to popular AI tools and platforms (ChatGPT, Claude, Gemini, etc)
    3. New AI developer tools and frameworks
    4. Top trending AI repositories on GitHub this week (focus on new tools, models, frameworks)

    Focus on concrete releases, updates and trending projects. Provide links where relevant. Skip speculation or minor news."""
    )

    return response.content


# Define a function to shuffle options within each question
def shuffle_options(mcq_list):
    """
    Shuffle options for quiz questions, supporting both QuizQuestionList and list of questions
    """
    # If mcq_list is a QuizQuestionList, use its questions
    if hasattr(mcq_list, 'questions'):
        questions = mcq_list.questions
    # If mcq_list is already a list of questions, use it directly
    elif isinstance(mcq_list, list):
        questions = mcq_list
    else:
        raise ValueError("Input must be a QuizQuestionList or a list of questions")

    shuffled_questions = []
    for mcq in questions:
        # Create a copy of the question to avoid modifying the original
        mcq_copy = mcq.model_copy()
        # Shuffle the options for each question
        random.shuffle(mcq_copy.options)
        shuffled_questions.append(mcq_copy)

    return shuffled_questions


def insert_quiz_questions(questions: Union[QuizQuestionList, List[QuizQuestion]], content: str, supabase_key, supabase_url):
    """
    Convert QuizQuestion objects to a format suitable for Supabase insertion
    """

    # Initialize Supabase client for quiz question storage'
    url: str = supabase_url
    key: str = supabase_key
    client: Client = create_client(url, key)

    shuffled_mcq_list = shuffle_options(questions)
    for question in shuffled_mcq_list:
        question.metadata = {"content" : content}
        try:
            client.table("daily_genai_quiz").insert(question.model_dump()).execute()
        except Exception as e:
            print(f"An error occurred: {e}")


def generate_ai_news_quiz(content: str, num_questions: int, openai_api_key, supabase_key, supabase_url):
    """
    Generate AI news quiz using ChatOpenAI with structured output
    """
    # Initialize the language model

    os.environ['OPENAI_API_KEY'] = openai_api_key
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.7
    )

    # Structured prompt template
    prompt = PromptTemplate(
        template=
        """"Generate {num_questions} context-based multiple-choice quiz questions from the following news content:\n\n{content}\n\n"

        Guidelines:

        1. Question Structure:
            Each question must include a brief context or background related to the news item.
            Ensure the question text references specific details from the news to make it engaging and informative.

            Example Question:

            Nobel laureates Geoffrey Hinton and Demis Hassabis have emphasized the need for strong regulation of artificial intelligence (AI). Geoffrey Hinton, who recently warned of AI potentially surpassing human intelligence, was awarded the Nobel Prize in Physics for his work on what key AI technology?

        2. Answer Options:
            Provide four distinct multiple-choice options, including only one correct answer.
            Ensure the incorrect options are plausible but clearly distinguishable from the correct answer.

            Example Options:

            Options:
            - Advanced robotics
            - Artificial neural networks
            - Quantum computing
            - Machine learning frameworks
        
        3. Correct Answer:
            Clearly identify the correct answer in the response.
        
        4. News Context:
            Include a short "news_context" for each question, summarizing the relevant news item.
        
        5. Variety:
            Focus on unique aspects of the content to ensure a variety of topics and perspectives in the questions.

        - Questions should be elaborative, incorporating relevant background or situational details from the news to enhance understanding.
        - Responses should be returned in JSON format. 

        Please ensure the variety and elaboration make the questions engaging and informative."
        {format_instructions}""",
        input_variables=["content", "num_questions"],
        partial_variables={
            "format_instructions": PydanticOutputParser(pydantic_object=QuizQuestionList).get_format_instructions()
        }
    )

    try:
        # Generate all questions in one call
        chain = prompt | llm | PydanticOutputParser(pydantic_object=QuizQuestionList)
        quiz_result = chain.invoke({
            "content": content,
            "num_questions": num_questions
        })

        # Ensure we have a QuizQuestionList or convert the result
        if isinstance(quiz_result, list):
            quiz_result = QuizQuestionList(questions=quiz_result)

        # Print for debugging
        print(f"Quiz Result Type: {type(quiz_result)}")
        print(f"Questions Count: {len(quiz_result.questions)}")

        # Push to Supabase
        if quiz_result.questions:
            # quiz_repo = SupabaseQuizRepository()
            insert_quiz_questions(quiz_result.questions, content, supabase_key, supabase_url)

        return quiz_result.questions

    except Exception as e:
        print(f"Error generating quiz questions: {e}")
        # If possible, print the traceback for more detailed error information
        import traceback
        traceback.print_exc()
        return []
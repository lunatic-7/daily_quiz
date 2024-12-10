import os
from datetime import date, datetime
import asyncio
from typing import List

from fastapi import FastAPI, BackgroundTasks

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx

from datetime import datetime
from pydantic import BaseModel
import uvicorn
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.

# Import the existing quiz generation logic
from .quiz_generator import generate_news, generate_ai_news_quiz, QuizQuestion, generate_news_scrape

# Environment Configuration
class Settings(BaseModel):
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY')
    PERPLEXITY_API_KEY: str = os.getenv('PERPLEXITY_API_KEY')
    SUPABASE_URL: str = os.getenv('SUPABASE_URL_BF')
    SUPABASE_KEY: str = os.getenv('SUPABASE_KEY_BF')
    SMTP_HOST: str = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT: int = int(os.getenv('SMTP_PORT', 587))
    SMTP_USERNAME: str = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD: str = os.getenv('SMTP_PASSWORD')
    NOTIFICATION_EMAIL: str = os.getenv('NOTIFICATION_EMAIL')

settings = Settings()

app = FastAPI()
scheduler = AsyncIOScheduler()

async def send_email_notification(subject: str, body: str):
    """
    Send email notification about quiz generation status
    """
    try:
        # Create message container
        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_USERNAME
        msg['To'] = settings.NOTIFICATION_EMAIL
        msg['Subject'] = subject

        # Attach body to email
        msg.attach(MIMEText(body, 'plain'))

        # Create SMTP session
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()  # Enable security
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
        
        print("Email notification sent successfully")
    except Exception as e:
        print(f"Failed to send email notification: {e}")

async def generate_daily_quiz():
    """
    Background task to generate daily AI news quiz
    """
    try:
        today = date.today().strftime("%dth %B, %Y")
        
        # news_content = generate_news(
        #     today, 
        #     perplexity_api_key=settings.PERPLEXITY_API_KEY
        # )

        news_content = generate_news_scrape()
        
        if news_content:
            print("News generated")
        generated_quiz = generate_ai_news_quiz(
            news_content, 
            num_questions=20,
            openai_api_key=settings.OPENAI_API_KEY,
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_KEY
        )
        if generated_quiz:
            print("Quiz generated")
        
        # Prepare email body
        email_body = f"""
        Daily AI News Quiz Generation Report
        Date: {today}
        
        Status: {'Success' if generated_quiz else 'Failed'}
        Number of Questions Generated: {len(generated_quiz)}
        
        News Context:
        {news_content}
        """
        
        # Send success/failure notification
        await send_email_notification(
            "Daily AI News Quiz Generation Report", 
            email_body
        )
        
        return generated_quiz
    except Exception as e:
        # Send error notification
        await send_email_notification(
            "Daily AI News Quiz Generation Error", 
            f"An error occurred during quiz generation: {str(e)}"
        )
        return []

@app.post("/generate-quiz")
async def trigger_quiz_generation(background_tasks: BackgroundTasks):
    """
    Endpoint to trigger quiz generation
    """
    background_tasks.add_task(generate_daily_quiz)
    return {
        "status": "Quiz generation initiated",
        "message": "Quiz will be generated and pushed to database"
    }

async def trigger_quiz_generation():
    async with httpx.AsyncClient() as client:
        response = await client.post("http://buildfast-dailyquiz/generate-quiz")
        print(f"Quiz generation triggered. Response: {response.text}")

# Schedule the quiz generation to run daily at 1:00 AM
scheduler.add_job(trigger_quiz_generation, CronTrigger.from_crontab("0 1 * * *"))

@app.on_event("startup")
async def startup_event():
    scheduler.start()
@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()


@app.get("/")
async def root():
    """
    Health check endpoint
    """
    return {
        "status": "healthy", 
        "message": "Daily AI News Quiz Generation API is running"
    }

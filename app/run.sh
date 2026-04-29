#!/bin/bash

if [ "$DEBUG" = "1" ]; then
  streamlit run /app/interview_prep_app.py --logger.level=debug --client.showErrorDetails=true
else
  streamlit run /app/interview_prep_app.py
fi

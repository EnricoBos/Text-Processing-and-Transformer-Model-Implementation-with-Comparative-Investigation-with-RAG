# -*- coding: utf-8 -*-
"""
Created on Sun Sep 22 15:52:26 2024

@author: Enrico
"""

import openai
from langchain.vectorstores import FAISS
#from langchain.embeddings import OpenAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import RetrievalQA
from langchain.schema import Document
from langchain.llms import OpenAI
import sys
import re
import pickle
from TransformerModel_with_classes import Transformer
import tensorflow as tf
### implementing a simple RAG 

###############################################################################
def clean_text(text):
    # Remove lines related to the metadata
    cleaned_text = re.sub(r"Generated by ABC Amber LIT Converter.*?\n", "", text)
    
    # Remove URLs from the text
    cleaned_text = re.sub(r"http[s]?://\S+|www\.\S+", "", cleaned_text)
    
    # Remove empty lines or excessive whitespace
    cleaned_text = re.sub(r"\n\s*\n", "\n", cleaned_text)
    
    # Remove page numbers and unwanted parts
    cleaned_text = re.sub(r'\bPage \d+\b', '', cleaned_text)  # Remove page numbers
    cleaned_text = re.sub(r'\bCHAPTER\b.*', '', cleaned_text)  # Remove chapter titles 
    
    # Remove excess whitespace
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()  
    
    # Extract only the relevant content starting from the first chapter
    start_index = cleaned_text.find("CHAPTER ONE")
    if start_index != -1:
        cleaned_text = cleaned_text[start_index:]
    
    return cleaned_text.strip()


MAX_LENGTH = 350
def evaluate(inp_sentence, model, tokenizer_q, tokenizer_a):
    start_token = [tokenizer_q.vocab_size()]
    end_token = [tokenizer_q.vocab_size() + 1]

    # Add start and end token to the input question
    inp_sentence = start_token + tokenizer_q.encode(inp_sentence) + end_token
    encoder_input = tf.expand_dims(inp_sentence, 0)  # add batch=1

    # Start token for decoder
    decoder_input = [tokenizer_a.vocab_size()]
    decoder_input = tf.expand_dims(decoder_input, 0)

    for i in range(MAX_LENGTH):
        # Get predictions from model
        predictions = model(encoder_input, decoder_input, False)

        # Get the last token's prediction
        predictions = predictions[:, -1:, :]  # (batch_size, 1, vocab_size)

        # Get the token with the highest probability
        predicted_id = tf.cast(tf.argmax(predictions, axis=-1), tf.int32)

        # Check if we hit the end token
        if tf.equal(predicted_id, tokenizer_a.vocab_size() + 1):
            print(f"=============\nGot end token\n=============")
            return tf.squeeze(decoder_input, axis=0)

        # Concatenate the predicted token to decoder_input
        decoder_input = tf.concat([decoder_input, predicted_id], axis=-1)

    return tf.squeeze(decoder_input, axis=0)


def reply(sentence, transformer,  tokenizer_q, tokenizer_a):
    result = evaluate(sentence, transformer,  tokenizer_q, tokenizer_a)
    #breakpoint()
    # Convert the result tensor to a NumPy array
    result_array = result.numpy()
     
    # Get the vocabulary size once
    vocab_size = tokenizer_a.vocab_size()
     
    # Decode the predicted sentence
    predicted_sentence = tokenizer_a.Decode(
         [int(i) for i in result_array if i < vocab_size])
    
    return sentence, predicted_sentence
###############################################################################

if __name__ == "__main__":
    choice = ''#'rag' #'comparison' --> set you choice
    # Set up OpenAI API key
    openai.api_key = 'YOUR OPENAI API'
    # OpenAI instance
    llm = OpenAI(temperature=0.7, api_key=openai.api_key) 
    embedding_model = OpenAIEmbeddings(api_key=openai.api_key)  # Use OpenAI to generate embeddings (numerical matrix) for chunks
    ###############################################################################
    folder_save_rag = './rag/'
    folder_transformer_model ='./transformer_model/'
    if(choice == 'rag'):
        print('Starting RAG pipeline..')
        # Test LLM connection
        try:
            # Example prompt
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is the capital of France?"}
                ],
                max_tokens=30  # Reduced to 30 to lower the token usage
            )
        
            # Print the output
            print(response.choices[0].message.content.strip())
            print("LLM Connection Successful!")
        except Exception as e:
            print("Failed")
            sys.exit()
        ###########################################################################
        ### document path
        path_txt = './hatty_potter/harry1.txt'
        
        # Manually load the text
        with open(path_txt, "r",  encoding="utf-8", errors="ignore") as file:
            text_raw = file.read()
        ### Step 1 clening
        text_content = clean_text(text_raw)
        ### Step 2 Wrap the content in LangChain's document format
        documents = [Document(page_content=text_content)] ## 
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,  # Experiment with larger sizes
            chunk_overlap=50,  # Adjust overlap to retain more context
            separators=["\n\n", ". ", "! ", "? "]  # Split based on sentence boundaries
        )
        
        chunks = text_splitter.split_documents(documents)
        # Extract text from Document objects
        texts = [chunk.page_content for chunk in chunks]

        # Step 2: Create a Vector Store (using FAISS with OpenAI embeddings)
        
        vector_store = FAISS.from_texts(texts, embedding_model) # FAISS creates an index of these vectors (stores these vectors efficiently)
        
        # Step 3: Set Up a RAG Chain 
        retriever = vector_store.as_retriever()
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="map_reduce",  # "stuff" chain_type for small documents, "map_reduce" for larger ones
            retriever=retriever, #  retriever (created from FAISS) receives the question, converts it into an embedding, and searches through the FAISS index to find the most semantically similar text chunks
            return_source_documents=True #  the chain will also return the actual chunk of doc that were used to generate the answe
        )
        
        ##### save data 
        # Save chunks to a file
        with open(folder_save_rag+"chunks.pkl", "wb") as f:
            pickle.dump(chunks, f)
        # Save the FAISS index to disk
        vector_store.save_local(folder_save_rag+"faiss_index")
        #####
        # Step 4: Define a Question and Generate Answer using RAG --> just for test
        question = "What is the significance of the Mirror of Erised, and what does it show Harry when he looks into it?"
        rag_answer = rag_chain.invoke(question)
        
        # Accessing the results
        answer = rag_answer.get('result')
        source_documents = rag_answer.get('source_documents')
        
        print("RAG Answer:", answer)
        if source_documents:
            print("Source Document:", source_documents[0])  # Print only the first document
    ### comparison btw transformer from scratch and RAG
    elif(choice == 'comparison'):
        print('Starting comparison btw transformer model from scratch and RAG')
        ### load "rag" file
        # Load chunks from a file
        with open(folder_save_rag + "chunks.pkl", "rb") as f:
            loaded_chunks = pickle.load(f)
    
        print(f"Loaded {len(loaded_chunks)} chunks.")
        
        # Load the FAISS index from disk
        vector_store = FAISS.load_local(folder_save_rag + "faiss_index",embedding_model, allow_dangerous_deserialization=True)
        
        print("FAISS index loaded successfully.")
        
        ### load trained transformer model data ###############################
        num_layers = 2 #2 number of encoder and decoder layers
        units = 512 #  dimensionality of the feedforward network (FFN) in the encoder and decoder layers. 
        d_model = 256 #  dimensionality of the embedding vectors
        num_heads = 8
        dropout = 0.2 #  0.1 means that 10% of the inputs to a given layer are set to zero
        train_dataset = val_dataset=  []
        ### load data tokenized
        with open('data_tokenized/data_token.pickle', 'rb') as handle:
            data = pickle.load(handle)

        #train = data['train']
        #validation = data['validation']
        tokenizer_q = data['tokenizer_q']
        tokenizer_a = data['tokenizer_a']
        input_vocab_size = tokenizer_q.vocab_size() + 2
        target_vocab_size = tokenizer_a.vocab_size() + 2
        transformer_model = Transformer(input_vocab_size, target_vocab_size , num_layers, units, d_model, num_heads, dropout)
        
        # Run a dummy input through the model to create the variables
        dummy_input = tf.random.uniform((64, 27), dtype=tf.int64, minval=0, maxval=200)
        dummy_target = tf.random.uniform((64, 27), dtype=tf.int64, minval=0, maxval=200)
        dummy_out = transformer_model(dummy_input ,dummy_target, False)
        transformer_model.load_weights('final_weights.h5')
        
        print('Transformer model loaded successfully.')
        #######################################################################
        # Set up the retriever and RAG chain
        retriever = vector_store.as_retriever()
        
        rag_chain = RetrievalQA.from_chain_type(
              llm=llm,
              chain_type="map_reduce",
              retriever=retriever,
              return_source_documents=False
          )
        
        #############COMPARISON###############################################
        ### custom questions ###################################################
        qa_vocabulary = {
            "What is the significance of the Mirror of Erised, and what does it show Harry when he looks into it?": "The Mirror of Erised shows the deepest desires of a person's heart. When Harry looks into the mirror, he sees his parents, who died when he was a baby.",
            "Who is the headmaster of Hogwarts during Harry's first year?": "Albus Dumbledore",
            "How does Harry Potter initially discover that he is a wizard in Harry Potter and the Sorcerer's Stone, and what role does Hagrid play in this revelation?":"Harry discovers he is a wizard when he receives a letter delivered by Hagrid, who comes to find him on his birthday. Hagrid explains Harry’s magical heritage and his acceptance into Hogwarts School of Witchcraft and Wizardry, revealing the truth about his identity and the magical worl",
            "What is the name of the dark wizard who tried to kill Harry as a baby?": "The dark wizard's name is Lord Voldemort, who was responsible for the deaths of Harry's parents and attempted to kill Harry himself.",
            "What is the significance of the Sorting Hat ceremony at Hogwarts?":"The Sorting Hat ceremony determines which house each new student at Hogwarts will join, shaping their friendships and experiences during their time at the school."
        }
       
        # my Transformer and RAG comparison
        for cq, actual_answer in qa_vocabulary.items():
            ### processing the string 
            # cq = preprocess_text(cq)
            input_sentence, pred_string = reply(cq, transformer_model, tokenizer_q, tokenizer_a)
            rag_answer = rag_chain.invoke(cq) 
            # Accessing the results
            ranswer = rag_answer.get('result')
            
            print(f"{'-'*40}")
            print(f"{' Question: ':*^40}")
            print(f"{'-'*40}")
            print(f"Input                 : {cq}")
            #print(f"Expected Answer       : {actual_answer}")
            print(f"Transformer Predicted : {pred_string}")
            print(f"RAG Predicted         : {ranswer}")
            print(f"{'-'*40}\n")
        
 
    
        
        

import os
# import random
import re

import numpy as np
# from keras.callbacks import ModelCheckpoint
from keras.layers import LSTM, Dense, Input  # , Reshape
from keras.models import Model  # , load_model
# from tensorflow import keras

custom = True

os.add_dll_directory("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v10.1\\bin")
os.add_dll_directory("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v10.1\\libnvvp")
os.add_dll_directory("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v10.1")
os.add_dll_directory("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v10.1\\extras\\CUPTI\\lib64")
os.add_dll_directory("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v10.1\\include")
os.add_dll_directory("C:\\tools\\cuda\\bin")
os.add_dll_directory("C:\\tools\\cuda")
os.add_dll_directory("C:\\Program Files\\NVIDIA Corporation\\Nsight Compute 2019.4.0")

if custom is True:
  data_path = "ml/intent_human.txt"
  data_path2 = "ml/intent_robot.txt"
else:
  data_path = "ml/human_text.txt"
  data_path2 = "ml/robot_text.txt"
# Defining lines as a list of each line
with open(data_path, 'r', encoding='utf-8') as f:
  lines = f.read().split('\n')
with open(data_path2, 'r', encoding='utf-8') as f:
  lines2 = f.read().split('\n')
lines = [re.sub(r"\[\w+\]", 'hi', line) for line in lines]
lines = [" ".join(re.findall(r"\w+", line)) for line in lines]
lines2 = [re.sub(r"\[\w+\]", '', line) for line in lines2]
lines2 = [" ".join(re.findall(r"\w+", line)) for line in lines2]
# grouping lines by response pair
pairs = list(zip(lines, lines2))
# random.shuffle(pairs)


def start(pairss):
  inp_docs = []
  target_docs = []
  inp_tokens = set()
  target_tokens = set()
  if custom is False:
    pairss = pairss[:800]
  for line in pairss:
    # for line in pairs[:1500]:
    inp_doc, target_doc = line[0], line[1]
    # Appending each inp sentence to inp_docs
    inp_docs.append(inp_doc)
    # Splitting words from punctuation
    target_doc = " ".join(re.findall(r"[\w']+|[^\s\w]", target_doc))
    # Redefine target_doc below and append it to target_docs
    target_doc = '<START> ' + target_doc + ' <END>'
    target_docs.append(target_doc)

    # Now we split up each sentence into words and add each unique word to our vocabulary set
    for token in re.findall(r"[\w']+|[^\s\w]", inp_doc):
      if token not in inp_tokens:
        inp_tokens.add(token)
    for token in target_doc.split():
      if token not in target_tokens:
        target_tokens.add(token)
  inp_tokens = sorted(list(inp_tokens))
  target_tokens = sorted(list(target_tokens))
  num_enc_tokens = len(inp_tokens)
  num_dec_tokens = len(target_tokens)

  inp_features_dict = dict(
      [(token, i) for i, token in enumerate(inp_tokens)])
  target_features_dict = dict(
      [(token, i) for i, token in enumerate(target_tokens)])
  # reverse_inp_features_dict = dict(
  #   (i, token) for token, i in inp_features_dict.items())
  # reverse_target_features_dict = dict(
  #   (i, token) for token, i in target_features_dict.items())

  # Maximum length of sentences in inp and target documents
  max_enc_seq_length = max(
      [len(re.findall(r"[\w']+|[^\s\w]", inp_doc)) for inp_doc in inp_docs])
  max_dec_seq_length = max(
      [len(re.findall(r"[\w']+|[^\s\w]", target_doc)) for target_doc in target_docs])
  enc_inp_data = np.zeros(
      (len(inp_docs), max_enc_seq_length, num_enc_tokens),
      dtype='float32')
  dec_inp_data = np.zeros(
      (len(inp_docs), max_dec_seq_length, num_dec_tokens),
      dtype='float32')
  dec_target_data = np.zeros(
      (len(inp_docs), max_dec_seq_length, num_dec_tokens),
      dtype='float32')
  for line, (inp_doc, target_doc) in enumerate(zip(inp_docs, target_docs)):
    for timestep, token in enumerate(re.findall(r"[\w']+|[^\s\w]", inp_doc)):
      # Assign 1. for the current line, timestep, & word in enc_inp_data
      enc_inp_data[line, timestep, inp_features_dict[token]] = 1.

    for timestep, token in enumerate(target_doc.split()):
      dec_inp_data[line, timestep, target_features_dict[token]] = 1.
      if timestep > 0:
        dec_target_data[line, timestep - 1, target_features_dict[token]] = 1.
  # Dimensionality
  dimensionality = 256
  # enc
  enc_inps = Input(shape=(None, num_enc_tokens))
  # enc_inps = Input(shape=(None, len(pairs)))
  enc_lstm = LSTM(dimensionality, return_state=True)
  # enc_outs,
  state_hidden, state_cell = enc_lstm(enc_inps)[1:]
  enc_states = [state_hidden, state_cell]
  # dec
  dec_inps = Input(shape=(None, num_dec_tokens))
  # dec_inps = Input(shape=(None, len(pairs)))
  dec_lstm = LSTM(dimensionality, return_sequences=True, return_state=True)
  dec_outs = dec_lstm(dec_inps, initial_state=enc_states)[0]
  dec_dense = Dense(num_dec_tokens, activation='softmax')
  dec_outs = dec_dense(dec_outs)

  del pairss
  return (
      enc_inp_data,
      dec_inp_data,
      dec_target_data,
      enc_inps,
      dec_inps,
      dec_outs,
      num_enc_tokens,
      num_dec_tokens
  )


# chunks = [":500","500:1000","1000:1500","1500:2000","2000:"]
# chunks = [[0,500],[500,1000],[1000,1500],[1500,2000],[2000,-1]]
# i = 0
# while i < len(chunks):
  # print(chunks[i])
# enc_inp_data,dec_inp_data,dec_target_data,enc_inps,dec_inps,dec_outs,epochs,batch_size = start(pairs[slice(chunks[i][0],chunks[i][1])])
enc_inp_data, dec_inp_data, dec_target_data, enc_inps, dec_inps, dec_outs, num_enc_tokens, num_dec_tokens = start(pairs)
# if i > 0:
#   training_model = load_model("full_training_model_0.h5")
#   training_model.layers[0] = Reshape(enc_inp_data.shape)
# else:
training_model = Model([enc_inps, dec_inps], dec_outs)
# print(training_model.layers[0].inp.reshape(enc_inp_data.shape))
# print(enc_inp_data.shape)
# Compiling
training_model.compile(optimizer='rmsprop', loss='categorical_crossentropy', metrics=['accuracy'], sample_weight_mode='temporal')
# print(enc_inp_data,dec_inp_data,dec_target_data)
# Training
training_model.fit(
    [enc_inp_data, dec_inp_data],
    dec_target_data,
    batch_size=10,
    epochs=300,
    workers=8,
    shuffle=True,
    use_multiprocessing=True)  # verbose=2,   validation_split = 0.2
# training_model.build(enc_inp_data.shape)
training_model.summary()
scores = training_model.evaluate([enc_inp_data, dec_inp_data], dec_target_data, verbose=0)
print("Accuracy: %.2f%%" % (scores[1] * 100))
# training_model.save('full_training_model_0.h5')
# del enc_inp_data,dec_inp_data,dec_target_data,enc_inps,dec_inps,dec_outs,epochs,batch_size
# i += 1


# Model
# # scores = training_model.evaluate([enc_inp_data[:500], dec_inp_data[:500]], dec_target_data[:500], verbose=0)
# # print("Baseline Error: &.2f%%" % (100-scores[1]*100))

# training_model.save("partly_trained.h5")
# del training_model

# training_model = load_model("partly_trained.h5")

# training_model.fit(
# [enc_inp_data[500:1000],
# dec_inp_data[500:1000]],
# dec_target_data[500:1000],
# batch_size = batch_size,
# epochs = epochs,
# validation_split = 0.2,
# shuffle=True,
# use_multiprocessing = True)
# training_model.save("partly_trained-1.h5")
# filepath="weights-improvement-{epoch:02d}-{accuracy:.4f}.hdf5"
# checkpoint = ModelCheckpoint(filepath, monitor='accuracy', verbose=1, save_best_only=True, mode='min')
# callbacks_list = [checkpoint]
# training_model.fit(
# [enc_inp_data, dec_inp_data],
# dec_target_data,
# batch_size = batch_size, epochs = epochs,
# callbacks=callbacks_list,
# validation_split = 0.2,
# shuffle=True,
# use_multiprocessing = True)

# print(enc_inps)
# print(enc_inp_data)

# class MY_Generator(keras.utils.Sequence):
#     def __init__(self,enc_inp_data,dec_inp_data,dec_target_data,batch_size):
#         self.enc_inp_data, self.dec_inp_data, self.dec_target_data = enc_inp_data,dec_inp_data,dec_target_data
#         self.batch_size = batch_size
#     def __len__(self):
#         return np.ceil(num_enc_tokens / int(self.batch_size)).astype(np.int)
#     def __getitem__(self,idx):
#         batch_x = self.enc_inp_data[idx * self.batch_size:(idx + 1) * self.batch_size]
#         batch_y = self.dec_inp_data[idx * self.batch_size:(idx + 1) * self.batch_size]
#         batch_z = self.dec_target_data[idx * self.batch_size:(idx + 1) * self.batch_size]

#         # return np.array([batch_x, batch_y], batch_z)
#         print(np.array(batch_x),np.array(batch_y),np.array(batch_z))
#         return np.array(batch_x),np.array(batch_y),np.array(batch_z)
# class MY_Generator_two(keras.utils.Sequence):
#     def __init__(self,inp_data,target_data,batch_size):
#         self.inp_data,self.target_data = inp_data,target_data
#         self.batch_size = batch_size
#     def __len__(self):
#         return np.ceil(num_enc_tokens / int(self.batch_size)).astype(np.int)
#     def __getitem__(self,idx):
#         batch_x = self.inp_data[idx * self.batch_size:(idx + 1) * self.batch_size]
#         batch_y = self.target_data[idx * self.batch_size:(idx + 1) * self.batch_size]

#         # return np.array([batch_x, batch_y], batch_z)
#         return np.array(batch_x),np.array(batch_y)

# class MY_Generator(keras.utils.Sequence):
#     def __init__(self,inp_data,batch_size):
#         self.inp_data = inp_data
#         self.batch_size = batch_size
#     def __len__(self):
#         return np.ceil(num_enc_tokens / int(self.batch_size)).astype(np.int)
#     def __getitem__(self,idx):
#         batch_x = self.inp_data[idx * self.batch_size:(idx + 1) * self.batch_size]

#         # return np.array([batch_x, batch_y], batch_z)
#         return np.array(batch_x)

# my_training_batch_generator_enc_inp_data = MY_Generator_two(enc_inp_data,dec_inp_data,batch_size)
# my_training_batch_generator_dec_target_data = MY_Generator(dec_target_data,batch_size)

# # print(my_training_batch_generator)
# training_model.summary()
# training_model.fit(my_training_batch_generator_enc_inp_data,my_training_batch_generator_dec_target_data, verbose = 1, epochs = epochs, shuffle=True, use_multiprocessing = True, max_queue_size=32)
if custom is True:
  training_model.save('ml/models/custom_gen_model.h5')
else:
  training_model.save('ml/models/gen_model.h5')


# training_model = load_model('custom_training_model_quick.h5')
# enc_inps = training_model.inp[0]
# enc_outs, state_h_enc, state_c_enc = training_model.layers[2].out
# enc_states = [state_h_enc, state_c_enc]
# enc_model = Model(enc_inps, enc_states)

# latent_dim = 256
# dec_state_inp_hidden = Input(shape=(latent_dim,))
# dec_state_inp_cell = Input(shape=(latent_dim,))
# dec_states_inps = [dec_state_inp_hidden, dec_state_inp_cell]

# dec_outs, state_hidden, state_cell = dec_lstm(dec_inps, initial_state=dec_states_inps)
# dec_states = [state_hidden, state_cell]
# dec_outs = dec_dense(dec_outs)

# dec_model = Model([dec_inps] + dec_states_inps, [dec_outs] + dec_states)

# def decode_response(test_inp):
#   #Getting the out states to pass into the dec
#   states_value = enc_model.predict(test_inp)
#   #Generating empty target sequence of length 1
#   target_seq = np.zeros((1, 1, num_dec_tokens))
#   #Setting the first token of target sequence with the start token
#   target_seq[0, 0, target_features_dict['<START>']] = 1.

#   #A variable to store our response word by word
#   decoded_sentence = ''

#   stop_condition = False
#   while not stop_condition:
#     #Predicting out tokens with probabilities and states
#     out_tokens, hidden_state, cell_state = dec_model.predict([target_seq] + states_value)
#     #Choosing the one with highest probability
#     sampled_token_index = np.argmax(out_tokens[0, -1, :])
#     sampled_token = reverse_target_features_dict[sampled_token_index]
#     decoded_sentence += " " + sampled_token
#     #Stop if hit max length or found the stop token
#     if (sampled_token == '<END>' or len(decoded_sentence) > max_dec_seq_length):
#       stop_condition = True
#       #Update the target sequence
#     target_seq = np.zeros((1, 1, num_dec_tokens))
#     target_seq[0, 0, sampled_token_index] = 1.
#     #Update states
#     states_value = [hidden_state, cell_state]
#   return decoded_sentence


# class ChatBot:
#   negative_responses = ("no", "nope", "nah", "naw", "not a chance", "sorry")
#   exit_commands = ("quit", "pause", "exit", "goodbye", "bye", "later", "stop")
# #Method to start the conversation
#   def start_chat(self):
#     user_response = inp("Hi, I'm a chatbot trained on random dialogs. Would you like to chat with me?\n")

#     if user_response in self.negative_responses:
#       print("Ok, have a great day!")
#       return
#     self.chat(user_response)
# #Method to handle the conversation
#   def chat(self, reply):
#     while not self.make_exit(reply):
#       reply = inp(self.generate_response(reply)+"\n")

#   #Method to convert user inp into a matrix
#   def string_to_matrix(self, user_inp):
#     tokens = re.findall(r"[\w']+|[^\s\w]", user_inp)
#     user_inp_matrix = np.zeros(
#       (1, max_enc_seq_length, num_enc_tokens),
#       dtype='float32')
#     for timestep, token in enumerate(tokens):
#       if token in inp_features_dict:
#         user_inp_matrix[0, timestep, inp_features_dict[token]] = 1.
#     return user_inp_matrix

#   #Method that will create a response using seq2seq model we built
#   def generate_response(self, user_inp):
#     inp_matrix = self.string_to_matrix(user_inp)
#     chatbot_response = decode_response(inp_matrix)
#     #Remove <START> and <END> tokens from chatbot_response
#     chatbot_response = chatbot_response.replace("<START>",'')
#     chatbot_response = chatbot_response.replace("<END>",'')
#     return chatbot_response
# #Method to check for exit commands
#   def make_exit(self, reply):
#     for exit_command in self.exit_commands:
#       if exit_command in reply:
#         print("Ok, have a great day!")
#         return True
#     return False

# chatbot = ChatBot()
# chatbot.start_chat()

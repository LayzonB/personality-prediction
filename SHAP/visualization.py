import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import numpy as np
import csv
import time
import pandas as pd
import utils.gen_utils as utils
import tensorflow as tf
import shap
import re
import preprocessor as p
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from PIL import Image

inp_dir, dataset_type, network, lr, batch_size, epochs, seed, write_file, embed, layer, mode, embed_mode = utils.parse_args()
mairesse, nrc, nrc_vad, affectivespace, hourglass, readability = utils.parse_args_SHAP()
n_classes = 2
np.random.seed(seed)
tf.compat.v1.set_random_seed(seed)
start = time.time()


def sentence_preprocess(sentence):
    sentence = p.clean(sentence)
    # Remove hyperlinks
    sentence = re.sub(r'http\S+', ' ', sentence)
    # Remove punctuations and numbers
    # sentence = re.sub('[^a-zA-Z]', ' ', sentence)
    sentence = re.sub('[^a-zA-Z.?!,]', ' ', sentence)
    # Single character removal (except I)
    sentence = re.sub(r"\s+[a-zA-HJ-Z]\s+", ' ', sentence)
    # Removing multiple spaces
    sentence = re.sub(r'\s+', ' ', sentence)
    return sentence


def load_features(dir):
    mairesse = pd.read_csv(dir + 'essays_mairesse_labeled.csv')
    mairesse = mairesse.set_index(mairesse.columns[0])
    nrc = pd.read_csv(dir + 'essays_nrc.csv').set_index(['#AUTHID'])
    nrc_vad = pd.read_csv(dir + 'essays_nrc-vad.csv').set_index(['#AUTHID'])
    # affectivespace = pd.read_csv(dir + 'essays_affectivespace.csv').set_index(['#AUTHID'])
    hourglass = pd.read_csv(dir + 'essays_hourglass.csv').set_index(['#AUTHID'])
    readability = pd.read_csv(dir + 'essays_readability.csv').set_index(['#AUTHID'])

    return [mairesse, nrc, nrc_vad, hourglass, readability]


def load_essays_df(datafile):
    with open(datafile, "rt") as csvf:
        csvreader = csv.reader(csvf, delimiter=',', quotechar='"')
        first_line = True
        df = pd.DataFrame(columns=["user", "text", "EXT", "NEU", "AGR", "CON", "OPN"])
        for line in csvreader:
            if first_line:
                first_line = False
                continue
            text = line[1]
            text = sentence_preprocess(text)

            df = df.append({"user": line[0],
                            "text": text,
                            "EXT": 1 if line[2].lower() == 'y' else 0,
                            "NEU": 1 if line[3].lower() == 'y' else 0,
                            "AGR": 1 if line[4].lower() == 'y' else 0,
                            "CON": 1 if line[5].lower() == 'y' else 0,
                            "OPN": 1 if line[6].lower() == 'y' else 0}, ignore_index=True)
    df = df.sample(frac=1)
    return df


def get_psycholinguist_data(dump_data):
    features = load_features('../data/essays/psycholinguist_features/')
    feature_flags = [mairesse, nrc, nrc_vad, hourglass, readability]
    first = 1
    for feature, feature_flag in zip(features, feature_flags):
        if feature_flag:
            if first:
                df = feature
                first = 0
            else:
                df = pd.merge(df, feature, left_index=True, right_index=True)
    labels = dump_data[['user', 'EXT', 'NEU', 'AGR', 'CON', 'OPN']]
    labels = labels.set_index('user')
    merged = pd.merge(df, labels, left_index=True, right_index=True).fillna(0)
    data = merged[merged.columns[:-5]].values
    full_targets = merged[merged.columns[-5:]].values
    feature_names = list(merged.columns)[:-5]
    for f in range(79):
        feature_names[f] = ' '.join(feature_names[f].split()[:-1])
    return data, full_targets, feature_names


def visualize(shap_vals, feature_names):
    vals = np.abs(shap_vals).mean(0)
    feature_importance = pd.DataFrame(list(zip(feature_names, sum(vals))),
                                      columns=['col_name', 'feature_importance_vals'])
    feature_importance.sort_values(by=['feature_importance_vals'], ascending=False, inplace=True)
    most_important = feature_importance['col_name'][:3].tolist()
    feature_importance = feature_importance.set_index(['col_name'])
    feature_importance_dict = feature_importance.to_dict()['feature_importance_vals']

    mask = np.array(Image.open('img.png'))
    wordcloud = WordCloud(width=1000, height=1000,
                          background_color='white',
                          mask=mask,
                          # min_font_size=10,
                          max_font_size=300,
                          max_words=128).generate_from_frequencies(feature_importance_dict)

    plt.figure(figsize=(8, 6), facecolor=None)
    plt.imshow(wordcloud)
    plt.axis("off")
    plt.tight_layout(pad=0)
    # plt.show()
    # wordcloud.to_file(labels_list[trait_idx] + "_wordcloud.png")
    plt.clf()

    # shap.summary_plot(shap_vals, feature_names=feature_names,
    #                   class_names=[labels_list[trait_idx] + ' 0', labels_list[trait_idx] + ' 1'])
    # shap.summary_plot(shap_vals, feature_names=feature_names, show=False, class_names=[labels_list[trait_idx]+' 0', labels_list[trait_idx]+' 1'], plot_size=(15,15))
    # plt.savefig(labels_list[trait_idx]+'-'+embed_mode+'-'+mode+".png")
    # plt.clf()
    return wordcloud, most_important


if __name__ == "__main__":
    dump_data = load_essays_df('../data/essays/essays.csv')
    labels_list = ['EXT', 'NEU', 'AGR', 'CON', 'OPN']
    data, full_targets, feature_names = get_psycholinguist_data(dump_data)
    # data, full_targets = get_bert_data()
    VOCAB_SIZE = 2000
    train_size = int(len(data) * .8)
    X_train = data[: train_size]
    X_test = data[train_size:]
    cloud_list = []
    MI_features = {}
    for trait_idx in range(full_targets.shape[1]):
        targets = full_targets[:, trait_idx]
        y_train = targets[: train_size]
        y_test = targets[train_size:]
        y_train = tf.keras.utils.to_categorical(y_train, num_classes=n_classes)
        y_test = tf.keras.utils.to_categorical(y_test, num_classes=n_classes)

        model = tf.keras.models.Sequential()
        model.add(tf.keras.layers.Dense(128, input_shape=(data.shape[-1],), activation='relu'))
        model.add(tf.keras.layers.Dense(50, activation='relu'))
        model.add(tf.keras.layers.Dense(2, activation='softmax'))
        model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])
        saver = tf.keras.callbacks.ModelCheckpoint('model' + str(trait_idx) + ".hdf5", save_best_only=True)
        model.fit(X_train, y_train, epochs=epochs, batch_size=batch_size, validation_split=0.1, callbacks=[saver])
        result = model.evaluate(X_test, y_test, batch_size=batch_size)
        print('Eval loss/accuracy:{}'.format(result))
        # file = open('results.txt', 'a')
        # file.write(str(trait_idx)+ ' : '+str(result)+'\n')
        # file.close()
        attrib_data = X_train
        explainer = shap.DeepExplainer(model, attrib_data)
        shap_vals = explainer.shap_values(X_test)
        cloud, MI_features_3 = visualize(shap_vals, feature_names)
        cloud_list.append(cloud)
        MI_features[labels_list[trait_idx]] = MI_features_3

    ocean_list = [cloud_list[4], cloud_list[3], cloud_list[0], cloud_list[2], cloud_list[1]]
    ocean_label_list = ['O', 'C', 'E', 'A', 'N']
    plt.figure(figsize=(15,4))
    for i in range(5):
        ax= plt.subplot(1,5,i+1)
        im=ax.imshow(ocean_list[i])
        plt.tight_layout()
        plt.title(ocean_label_list[i])
        plt.subplots_adjust(wspace=0.1)
        plt.axis("off")
    plt.show()
    print(MI_features)

    print('tammat')

from keras.layers import Conv2D, UpSampling2D, MaxPooling2D, Input,Permute,Reshape,ConvLSTM2D,Concatenate,GaussianNoise,BatchNormalization
from keras.layers.core import Lambda
from keras.models import Sequential, Model
from keras.callbacks import Callback
import random
import glob
import wandb
from wandb.keras import WandbCallback
import subprocess
import os
from PIL import Image
import numpy as np
from keras import backend as K

run = wandb.init(project='catz', entity='yyh')
config = run.config

config.num_epochs = 20
config.batch_size = 32
config.img_dir = "images"
config.height = 96
config.width = 96

val_dir = 'catz/test'
train_dir = 'catz/train'

# automatically get the data if it doesn't exist
if not os.path.exists("catz"):
    print("Downloading catz dataset...")
    subprocess.check_output(
        "curl https://storage.googleapis.com/wandb/catz.tar.gz | tar xz", shell=True)


class ImageCallback(Callback):
    def on_epoch_end(self, epoch, logs):
        validation_X, validation_y = next(
            my_generator(15, val_dir))
        output = self.model.predict(validation_X)
        wandb.log({
            "input": [wandb.Image(np.concatenate(np.split(c, 5, axis=2), axis=1)) for c in validation_X],
            "output": [wandb.Image(np.concatenate([validation_y[i], o], axis=1)) for i, o in enumerate(output)]
        }, commit=False)


def my_generator(batch_size, img_dir):
    """A generator that returns 5 images plus a result image"""
    cat_dirs = glob.glob(img_dir + "/*")
    counter = 0
    while True:
        input_images = np.zeros(
            (batch_size, config.width, config.height, 3 * 5))
        output_images = np.zeros((batch_size, config.width, config.height, 3))
        random.shuffle(cat_dirs)
        if ((counter+1)*batch_size >= len(cat_dirs)):
            counter = 0
        for i in range(batch_size):
            input_imgs = glob.glob(cat_dirs[counter + i] + "/cat_[0-5]*")
            imgs = [Image.open(img) for img in sorted(input_imgs)]
            input_images[i] = np.concatenate(imgs, axis=2)
            output_images[i] = np.array(Image.open(
                cat_dirs[counter + i] + "/cat_result.jpg"))
        yield (input_images, output_images)
        counter += batch_size

def get_last_img(img):
    return img[:,4,:,:,:]

def get_diff(img):
    return img[:,1:,:,:,:] - img[:,:4,:,:,:]

inp = Input(shape=(config.height,config.width,5*3))
reshape = Reshape((96,96,5,3))(inp)
perm = Permute((3,1,2,4))(reshape) # 5 96 96 3



last_img = Lambda(get_last_img)(perm)
diff_img = Lambda(get_diff)(perm)

gauss_noise_1 = GaussianNoise(1)(diff_img)
convlstm_1 = ConvLSTM2D(64,(3,3),activation='relu',padding='same',data_format='channels_last')(gauss_noise_1)
batchnorm_1 = BatchNormalization()(convlstm_1)

conv2d_1 = Conv2D(64,(3,3),activation='relu',padding='same')(batchnorm_1)
conv2d_2 = Conv2D(32,(3,3),activation='relu',padding='same')(conv2d_1)
conv2d_3 = Conv2D(16,(3,3),activation='relu',padding='same')(conv2d_2)


concat_1 = Concatenate()([last_img, conv2d_3])

conv2d_4 = Conv2D(3,(2,2),activation='relu',padding='same')(concat_1)

model = Model(inp,conv2d_4)

def perceptual_distance(y_true, y_pred):
    rmean = (y_true[:, :, :, 0] + y_pred[:, :, :, 0]) / 2
    r = y_true[:, :, :, 0] - y_pred[:, :, :, 0]
    g = y_true[:, :, :, 1] - y_pred[:, :, :, 1]
    b = y_true[:, :, :, 2] - y_pred[:, :, :, 2]

    return K.mean(K.sqrt((((512+rmean)*r*r)/256) + 4*g*g + (((767-rmean)*b*b)/256)))


model.compile(optimizer='adam', loss='mean_squared_error', metrics=[perceptual_distance])
model.summary()
model.fit_generator(my_generator(config.batch_size, train_dir),
                    steps_per_epoch=len(
                        glob.glob(train_dir + "/*")) // config.batch_size,
                    epochs=config.num_epochs, callbacks=[
    ImageCallback(), WandbCallback()],
    validation_steps=len(glob.glob(val_dir + "/*")) // config.batch_size,
    validation_data=my_generator(config.batch_size, val_dir))

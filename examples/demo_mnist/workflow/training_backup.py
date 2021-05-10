import mlflow
import click
import logging
import pandas as pd
import time
import torch
import mlflow.pytorch
import shutil
import torchvision
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torchvision.transforms as transforms
import random
import numpy as np
import os


from mlflow.tracking import MlflowClient
from mlflow.models.signature import infer_signature
from pathlib import Path
from torch.utils.data import DataLoader, Dataset
from torch.optim.lr_scheduler import StepLR

client = MlflowClient()

@click.command(help="Train the CNN model")
@click.option("--model_name", default='mnist_cnn', type=str)
@click.option("--x_train_path", default='./images', type=str)
@click.option("--y_train_path", default='./images', type=str)
@click.option("--x_test_path", default='./images', type=str)
@click.option("--y_test_path", default='./images', type=str)
def training(model_name, x_train_path, y_train_path, x_test_path, y_test_path):
    with mlflow.start_run(run_name='training') as mlrun:

        img_rows, img_cols = 28, 28
        x_train = np.load(x_train_path)
        y_train = np.load(y_train_path)

        x_test = np.load(x_test_path)
        y_test = np.load(y_test_path)

        x_train = x_train.reshape(x_train.shape[0], img_rows, img_cols)
        x_test = x_test.reshape(x_test.shape[0], img_rows, img_cols)
            
        model_mnist = fit_model(x_train, y_train, model_name=f'{model_name}.pt')
        mnist_score = evaluate(model_mnist, x_test, y_test)
        predictions = predict_model(model_mnist, x_test)
        
        signature = infer_signature(x_test, predictions)
        mlflow.pytorch.log_model(model_mnist, artifact_path=model_name, 
                                 signature=signature, 
                                 registered_model_name=model_name,
                                 input_example=x_test[:2])
        
#         client.transition_model_version_stage(
#             name="mnist_cnn",
#             version=1,
#             stage="Staging"
#         )  
        x_train_path = 'x_train.npy'
        y_train_path = 'y_train.npy'
        with open(x_train_path, 'wb') as f:
            np.save(f, x_train)
        with open(y_train_path, 'wb') as f:
            np.save(f, y_train)
            
        model_path = './model'
        if os.path.isdir(model_path):
            shutil.rmtree(model_path, ignore_errors=True)
        else:
            mlflow.pytorch.save_model(model_mnist, model_path)
            
        mlflow.log_metric(key='accuracy', value=round(mnist_score, 2))
        mlflow.log_param(key='x_len', value=x_train.shape[0])

#         mlflow.log_artifact(x_train_path, 'dataset')
        mlflow.log_artifact(x_train_path)
        mlflow.log_artifact(y_train_path)
        mlflow.log_artifact(x_test_path)
        mlflow.log_artifact(y_test_path)


class CNN(nn.Module):
    def __init__(self):
        super(CNN, self).__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, 1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)
        self.dropout1 = nn.Dropout2d(0.25)
        self.dropout2 = nn.Dropout2d(0.5)
        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = self.conv1(x)
        x = F.relu(x)
        x = self.conv2(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout1(x)
        x = torch.flatten(x, 1)
        x = self.fc1(x)
        x = F.relu(x)
        x = self.dropout2(x)
        x = self.fc2(x)
        output = F.log_softmax(x, dim=1)
        return output
    
def get_model_params():
    params = {
#       'batch_size': 16,
      'batch_size': 64,
      'test_batch_size': 1000,
      'epochs': 1,
      'lr': 1.0,
      'gamma': 0.7,
      'seed': 42,
      'log_interval': 100,
      'save_model': True
  }

    return params

def set_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    np.random.seed(seed)
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    
def get_device():
    return 'cuda' if torch.cuda.is_available() else 'cpu'


# Consider x and y
def get_dataloader(x, y, batch_size, transform, kwargs):
    
    class CustomDataset(Dataset):
        
        def __init__(self, x, y, transform=None):

            self.length = x.shape[0]
            self.x_data = x
            # self.x_data = torch.from_numpy(x)
            self.y_data = y
            # self.y_data = torch.from_numpy(y)
            self.transform = transform

        def __getitem__(self, index):
            x_data = self.x_data[index]

            if self.transform:
                x_data = self.transform(x_data)

            return (x_data, self.y_data[index])

        def __len__(self):
            return self.length

    train_dataset = CustomDataset(x, y, transform)
    train_loader = DataLoader(dataset=train_dataset, 
                              batch_size=batch_size, 
                              shuffle=True, **kwargs)
    
    return train_loader

def get_dataloader_x(x, batch_size, transform, kwargs):
    
    class CustomDataset(Dataset):
        
        def __init__(self, x, transform=None):

            self.length = x.shape[0]
            self.x_data = x
            # self.x_data = torch.from_numpy(x)
            # self.y_data = y
            # self.y_data = torch.from_numpy(y)
            self.transform = transform

        def __getitem__(self, index):
            x_data = self.x_data[index]

            if self.transform:
                x_data = self.transform(x_data)

            # return (x_data, self.y_data[index])
            return x_data

        def __len__(self):
            return self.length

    train_dataset = CustomDataset(x, transform)
    train_loader = DataLoader(dataset=train_dataset, 
                              batch_size=batch_size, 
                              shuffle=False, **kwargs)
    
    return train_loader

def predict_model(model, x):
    params = get_model_params()

    model.eval()
    device = get_device()
    
    kwargs = {'num_workers': 1, 'pin_memory': True}

    transform = transforms.Compose([
                            transforms.ToTensor(),
                            transforms.Normalize((0.1307,), (0.3081,))
                        ])

    test_loader = get_dataloader_x(x, params['test_batch_size'],
                                transform, kwargs)
  
    preds = []

    with torch.no_grad():
        for data in test_loader:
            data = data.to(device)
            output = model(data)
            pred = output.argmax(dim=1, keepdim=True)

            preds.extend(pred.cpu().detach().numpy().flatten())

    return np.array(preds)

def train_model(params, model, device, train_loader, optimizer, epoch):
    params = get_model_params()
    # torch.manual_seed(params['seed'])
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        target = target.type(torch.LongTensor)
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        
        loss = F.nll_loss(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % params['log_interval'] == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.item()))

def test_model(model, device, test_loader):
    params = get_model_params()
    # torch.manual_seed(params['seed'])
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            target = target.type(torch.LongTensor)
            data, target = data.to(device), target.to(device)
            
            output = model(data)
            test_loss += F.nll_loss(output, target, reduction='sum').item()  # sum up batch loss
            pred = output.argmax(dim=1, keepdim=True)  # get the index of the max log-probability
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)
    score = 100. * correct / len(test_loader.dataset)

    return round(score, 5)

def fit_model(x_train, y_train, model_name='mnist_cnn.pt'):

    params = get_model_params()

    device = get_device()
    # torch.manual_seed(params['seed'])
    set_seed(params['seed'])
    kwargs = {'num_workers': 1, 'pin_memory': True}


    transform = transforms.Compose([
                           transforms.ToTensor(),
                           transforms.Normalize((0.1307,), (0.3081,))
                       ])
    train_loader = get_dataloader(x_train, y_train, params['batch_size'],
                                transform, kwargs)

#     test_loader = get_dataloader(x_test, y_test, params['test_batch_size'],
#                                 transform, kwargs)

    model = CNN().to(device)
    optimizer = optim.Adadelta(model.parameters(), lr=params['lr'])

    scheduler = StepLR(optimizer, step_size=1, gamma=params['gamma'])
    for epoch in range(1, params['epochs'] + 1):
        train_model(params, model, device, train_loader, optimizer, epoch)
#         score = test_model(model, device, test_loader)
        scheduler.step()

    if params['save_model']:
        torch.save(model.state_dict(), model_name)  

    return model#, score

def evaluate(model, x_test, y_test):

    params = get_model_params()

    device = get_device()
    # torch.manual_seed(params['seed'])
    kwargs = {'num_workers': 1, 'pin_memory': True}
    transform = transforms.Compose([
                           transforms.ToTensor(),
                           transforms.Normalize((0.1307,), (0.3081,))
                       ])
    test_loader = get_dataloader(x_test, y_test, params['test_batch_size'],
                                transform, kwargs)

    score = test_model(model, device, test_loader)


    return score

if __name__ == '__main__':
    training()
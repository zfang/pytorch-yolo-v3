from __future__ import division

import argparse
import json
import os
import pickle as pkl
import random
import time

from darknet import Darknet
from preprocess import letterbox_image
from util import *


def get_test_input(input_dim, CUDA):
    img = cv2.imread("dog-cycle-car.png")
    img = cv2.resize(img, (input_dim, input_dim))
    img_ = img[:, :, ::-1].transpose((2, 0, 1))
    img_ = img_[np.newaxis, :, :, :] / 255.0
    img_ = torch.from_numpy(img_).float()
    img_ = Variable(img_)

    if CUDA:
        img_ = img_.cuda().half()

    return img_


def prep_image(img, inp_dim):
    """
    Prepare image for inputting to the neural network.

    Returns a Variable
    """

    orig_im = img
    dim = orig_im.shape[1], orig_im.shape[0]
    img = (letterbox_image(orig_im, (inp_dim, inp_dim)))
    img_ = img[:, :, ::-1].transpose((2, 0, 1)).copy()
    img_ = torch.from_numpy(img_).float().div(255.0).unsqueeze(0)
    return img_, orig_im, dim


def write(x, img, predictions=None):
    c1 = tuple(x[1:3].int())
    c2 = tuple(x[3:5].int())
    cls = int(x[-1])
    label = "{0}".format(classes[cls])
    color = random.choice(colors)
    cv2.rectangle(img, c1, c2, color, 1)
    t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 1, 1)[0]
    c2 = c1[0] + t_size[0] + 3, c1[1] + t_size[1] + 4
    cv2.rectangle(img, c1, c2, color, -1)
    cv2.putText(img, label, (c1[0], c1[1] + t_size[1] + 4), cv2.FONT_HERSHEY_PLAIN, 1, [225, 255, 255], 1);
    if predictions is not None:
        predictions.append(dict(label=label, coordinates=((c1[0].item(), c1[1].item()), (c2[0].item(), c2[1].item()))))
    return img


def arg_parse():
    """
    Parse arguements to the detect module

    """

    parser = argparse.ArgumentParser(description='YOLO v2 Video Detection Module')

    parser.add_argument("--video", dest='video', help=
    "Video to run detection upon",
                        default="video.avi", type=str)
    parser.add_argument("--dataset", dest="dataset", help="Dataset on which the network has been trained",
                        default="pascal")
    parser.add_argument("--confidence", dest="confidence", help="Object Confidence to filter predictions", default=0.5)
    parser.add_argument("--nms_thresh", dest="nms_thresh", help="NMS Threshhold", default=0.4)
    parser.add_argument("--cfg", dest='cfgfile', help=
    "Config file",
                        default="cfg/yolov3.cfg", type=str)
    parser.add_argument("--weights", dest='weightsfile', help=
    "weightsfile",
                        default="yolov3.weights", type=str)
    parser.add_argument("--reso", dest='reso', help=
    "Input resolution of the network. Increase to increase accuracy. Decrease to increase speed",
                        default="416", type=str)
    parser.add_argument("--write_output", action='store_true')
    parser.add_argument("--output_dir", default='.')
    return parser.parse_args()


if __name__ == '__main__':
    args = arg_parse()
    confidence = float(args.confidence)
    nms_thesh = float(args.nms_thresh)
    start = 0

    CUDA = torch.cuda.is_available()
    num_classes = 80
    bbox_attrs = 5 + num_classes

    print("Loading network.....")
    model = Darknet(args.cfgfile)
    model.load_weights(args.weightsfile)
    print("Network successfully loaded")

    model.net_info["height"] = args.reso
    inp_dim = int(model.net_info["height"])
    assert inp_dim % 32 == 0
    assert inp_dim > 32

    if CUDA:
        model.cuda().half()

    model(get_test_input(inp_dim, CUDA), CUDA)

    model.eval()

    videofile = args.video

    cap = cv2.VideoCapture(videofile)

    predictions_file = None
    if args.write_output:
        FRAME_WIDTH = cap.get(3)
        FRAME_HEIGHT = cap.get(4)
        FRAME_FPS = cap.get(5)
        FRAME_FOURCC = cap.get(6)
        FRAME_FOURCC_1 = cap.get(cv2.CAP_PROP_FOURCC)
        if not os.path.exists(args.output_dir):
            os.makedirs(args.output_dir, exists_ok=True)
        video_name, video_ext = os.path.splitext(os.path.basename(args.video))
        output_file = os.path.join(args.output_dir, 'result_{}{}'.format(video_name, '.avi'))
        predictions_file = os.path.join(args.output_dir, 'predictions_{}{}'.format(video_name, '.jsonl'))
        fourcc = cv2.VideoWriter_fourcc(*'MPEG')
        out = cv2.VideoWriter(output_file, int(FRAME_FOURCC), FRAME_FPS, (int(FRAME_WIDTH), int(FRAME_HEIGHT)))

        if os.path.exists(predictions_file):
            os.remove(predictions_file)

    assert cap.isOpened(), 'Cannot capture source'

    frames = 0
    start = time.time()
    while cap.isOpened():

        ret, frame = cap.read()
        if ret:

            img, orig_im, dim = prep_image(frame, inp_dim)

            im_dim = torch.FloatTensor(dim).repeat(1, 2)

            if CUDA:
                img = img.cuda().half()

            output = model(Variable(img, volatile=True), CUDA)
            output = write_results(output.type(torch.FloatTensor), confidence, num_classes, nms=True,
                                   nms_conf=nms_thesh)

            if type(output) == int:
                frames += 1
                print("FPS of the video is {:5.2f}".format(frames / (time.time() - start)))
                if args.write_output:
                    out.write(orig_im)
                else:
                    cv2.imshow("frame", orig_im)
                    key = cv2.waitKey(1)
                    if key & 0xFF == ord('q'):
                        break
                continue

            im_dim = im_dim.repeat(output.size(0), 1)
            scaling_factor = torch.min(inp_dim / im_dim, 1)[0].view(-1, 1)

            output[:, [1, 3]] -= (inp_dim - scaling_factor * im_dim[:, 0].view(-1, 1)) / 2
            output[:, [2, 4]] -= (inp_dim - scaling_factor * im_dim[:, 1].view(-1, 1)) / 2

            output[:, 1:5] /= scaling_factor

            for i in range(output.shape[0]):
                output[i, [1, 3]] = torch.clamp(output[i, [1, 3]], 0.0, im_dim[i, 0])
                output[i, [2, 4]] = torch.clamp(output[i, [2, 4]], 0.0, im_dim[i, 1])

            classes = load_classes('data/coco.names')
            colors = pkl.load(open("pallete", "rb"))

            predictions = []
            list(map(lambda x: write(x, orig_im, predictions), output))

            if args.write_output:
                out.write(orig_im)
                with open(predictions_file, 'a', encoding='utf8') as fout:
                    fout.write(json.dumps(dict(frame=frames, predictions=predictions)) + '\n')
            else:
                cv2.imshow("frame", orig_im)
                key = cv2.waitKey(1)
                if key & 0xFF == ord('q'):
                    break
            frames += 1
            print("FPS of the video is {:5.2f}".format(frames / (time.time() - start)))


        else:
            break
